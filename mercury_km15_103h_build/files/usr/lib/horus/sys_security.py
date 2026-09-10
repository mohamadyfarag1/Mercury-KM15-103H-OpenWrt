# -*- coding: utf-8 -*-
import subprocess
from .logutil import get_logger

log = get_logger("horus.sys_security")


def _wifi_iface_sections():
    """Return every wifi-iface section name (not just the first two).

    The old code hardcoded @wifi-iface[0] and [1], which silently errored on
    single-radio devices and missed the 3rd+ iface on tri-band / multi-SSID
    APs, so a banned client could still associate on an un-listed SSID.
    """
    try:
        out = subprocess.check_output("uci show wireless", shell=True, text=True)
        return [l.split('.', 1)[1].split('=', 1)[0]
                for l in out.splitlines() if l.endswith('=wifi-iface')]
    except Exception:
        return []


def _has_nft():
    """True on nftables/fw4 systems (OpenWrt 22.03+, kernel 5.10+)."""
    try:
        return subprocess.run("command -v nft >/dev/null 2>&1", shell=True).returncode == 0
    except Exception:
        return False


def _fw_drop_mac(mac):
    """Insert an L3 drop for a client MAC, on whichever firewall this
    kernel/OpenWrt ships: nftables (fw4) first, legacy iptables as fallback.

    On fw4 systems (default since 22.03) the `iptables` binary is usually
    absent, so the old unconditional `iptables -I FORWARD` was a silent no-op
    there. The primary ban is still the wireless MAC ACL + hostapd deauth
    above; this is the belt-and-suspenders L3 layer, made kernel-agnostic.
    """
    if _has_nft():
        try:
            # Skip if an identical rule already exists.
            chk = subprocess.run(
                f"nft -a list chain inet fw4 forward 2>/dev/null | grep -iq '{mac}'",
                shell=True)
            if chk.returncode != 0:
                subprocess.run(
                    f"nft insert rule inet fw4 forward ether saddr {mac} drop 2>/dev/null",
                    shell=True)
            return
        except Exception:
            pass
    try:
        chk = subprocess.run(
            f"iptables -C FORWARD -m mac --mac-source {mac} -j DROP 2>/dev/null",
            shell=True)
        if chk.returncode != 0:
            subprocess.run(
                f"iptables -I FORWARD 1 -m mac --mac-source {mac} -j DROP 2>/dev/null",
                shell=True)
    except Exception:
        pass


def _fw_undrop_mac(mac):
    """Remove the L3 drop for a MAC from both firewalls (harmless if absent)."""
    if _has_nft():
        try:
            listing = subprocess.check_output(
                "nft -a list chain inet fw4 forward 2>/dev/null", shell=True, text=True)
            for line in listing.splitlines():
                if mac.lower() in line.lower() and 'handle' in line:
                    handle = line.strip().split('handle')[-1].strip()
                    if handle.isdigit():
                        subprocess.run(
                            f"nft delete rule inet fw4 forward handle {handle} 2>/dev/null",
                            shell=True)
        except Exception:
            pass
    # Also clean up any legacy iptables rule (e.g. banned before a firmware upgrade).
    try:
        subprocess.run(
            f"iptables -D FORWARD -m mac --mac-source {mac} -j DROP 2>/dev/null",
            shell=True)
    except Exception:
        pass


def ban_mac_locally(mac):
    try:
        # 1. Hardware RF deauth & instant association rejection via hostapd ubus
        out = subprocess.check_output("ubus list | grep hostapd", shell=True, text=True)
        for h in out.splitlines():
            h = h.strip()
            if not h or not h.startswith("hostapd."): continue
            subprocess.run(f"ubus call {h} del_client '{{\"addr\":\"{mac}\", \"ban_time\": 0, \"deauth\": true}}'", shell=True)

        # 2. Hardware MAC ACL in Wireless configuration (drops probe requests & blocks auth)
        #    Applied to EVERY wifi-iface so the client can't hop to another SSID/band.
        try:
            changed = False
            for sec in _wifi_iface_sections():
                try:
                    raw_wl = subprocess.check_output(
                        f"uci -q get wireless.{sec}.maclist", shell=True, text=True).strip()
                except Exception:
                    raw_wl = ""
                if mac.lower() not in raw_wl.lower():
                    subprocess.run(f"uci -q set wireless.{sec}.macfilter='deny'", shell=True)
                    subprocess.run(f"uci -q add_list wireless.{sec}.maclist='{mac}'", shell=True)
                    changed = True
            if changed:
                subprocess.run("uci commit wireless", shell=True)
        except Exception:
            pass

        # 3. Layer 3 firewall drop (nftables/fw4 or legacy iptables)
        _fw_drop_mac(mac)
    except Exception:
        log.exception("ban_mac_locally failed for %s", mac)


def unban_mac_locally(mac):
    try:
        # 1. Remove from Hardware MAC ACL in every Wireless interface
        try:
            changed = False
            for sec in _wifi_iface_sections():
                subprocess.run(f"uci -q del_list wireless.{sec}.maclist='{mac}'", shell=True)
                changed = True
            if changed:
                subprocess.run("uci commit wireless", shell=True)
        except Exception:
            pass

        # 2. Remove Layer 3 firewall drop
        _fw_undrop_mac(mac)
    except Exception:
        log.exception("unban_mac_locally failed for %s", mac)
