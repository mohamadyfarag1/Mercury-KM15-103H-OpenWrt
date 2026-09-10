# -*- coding: utf-8 -*-
import os
import re
import sys
import json
import time
from .protocol import send_hmp_frame
from .system import (
    get_uci, get_hostname, get_lan_ip, get_wireless_macs,
    get_wifi_radios_and_macs, get_5g_channel_health
)

PEERS_FILE = "/tmp/horus_ap_peers.json"
PEER_TTL_MULTIPLIER = 3
PEER_TTL_MIN = 90

def calculate_peer_ttl(neighbors_interval):
    """How long a peer entry stays valid, always >= 3 announce intervals."""
    try:
        interval = int(neighbors_interval)
    except Exception:
        interval = 30
    return max(PEER_TTL_MIN, interval * PEER_TTL_MULTIPLIER)

def clear_peers_file():
    """Drop the P2P peer table when a controller takes over."""
    try:
        if os.path.exists(PEERS_FILE) and os.path.getsize(PEERS_FILE) > 2:
            tmp_p = PEERS_FILE + ".tmp"
            with open(tmp_p, "w") as f:
                json.dump({}, f)
            os.replace(tmp_p, PEERS_FILE)
    except Exception:
        pass

def sync_peer_host_hints(peers_db):
    """Ensure OpenWrt dnsmasq and LuCI getHostHints know about all P2P peers."""
    try:
        ethers_lines = []
        hosts_lines = []
        for mac, info in peers_db.items():
            ip = info.get("ip")
            host = info.get("hostname")
            if ip and ip != "0.0.0.0" and mac and mac != "00:00:00:00:00:00":
                ethers_lines.append(f"{mac} {ip}\n")
                # A friendly name may now be Arabic / contain spaces. dnsmasq
                # only accepts RFC-valid hostnames in /tmp/hosts, so only emit a
                # hosts entry when the name is valid; the ethers MAC↔IP mapping
                # (which needs no hostname) is still written either way.
                if host and re.match(r'^[A-Za-z0-9.-]{1,63}$', str(host)):
                    hosts_lines.append(f"{ip} {host}\n")
        
        if hosts_lines:
            os.makedirs("/tmp/hosts", exist_ok=True)
            with open("/tmp/hosts/horus_p2p.tmp", "w") as f:
                f.writelines(list(set(hosts_lines)))
            os.replace("/tmp/hosts/horus_p2p.tmp", "/tmp/hosts/horus_p2p")
        
        if ethers_lines:
            existing = set()
            if os.path.exists("/etc/ethers"):
                try:
                    with open("/etc/ethers", "r") as f:
                        for line in f:
                            existing.add(line.strip().upper())
                except Exception:
                    pass
            new_lines = []
            for el in ethers_lines:
                clean_el = el.strip().upper()
                if clean_el and clean_el not in existing:
                    new_lines.append(el)
                    existing.add(clean_el)
            if new_lines:
                with open("/etc/ethers", "a") as f:
                    f.writelines(new_lines)
        
        # Signal dnsmasq to reload /etc/hosts, /tmp/hosts, and /etc/ethers
        os.system("killall -HUP dnsmasq 2>/dev/null")
    except Exception:
        pass

def send_peer_announce(node):
    """Broadcast P2P presence announcement."""
    try:
        node.neighbors_enabled = get_uci("horus_controller.main.neighbors_enabled", "1") == "1"
        try:
            node.neighbors_interval = int(get_uci("horus_controller.main.neighbors_interval", "30"))
        except Exception:
            pass
        if not node.neighbors_enabled:
            return
        if node.is_controller_managed():
            clear_peers_file()
            return
        radios = get_wifi_radios_and_macs()
        health_5g = get_5g_channel_health()

        # Prioritize 5GHz wireless MAC so peer APs see the exact MAC connected to their wireless card!
        mac_5g = (radios.get("5g") and radios["5g"][0]) or ""
        mac_2g = (radios.get("2g") and radios["2g"][0]) or ""
        
        if mac_5g:
            primary_mac = mac_5g
        elif mac_2g:
            primary_mac = mac_2g
        else:
            primary_mac = node.my_mac

        all_macs = list(set(radios.get("all", []) + [node.my_mac, primary_mac]))
        if mac_5g and mac_5g not in all_macs: all_macs.append(mac_5g)
        if mac_2g and mac_2g not in all_macs: all_macs.append(mac_2g)

        payload = {
            "type": "peer_announce",
            "src_mac": primary_mac,
            "mac_5g": mac_5g,
            "mac_2g": mac_2g,
            "mac_lan": node.my_mac,
            # get_hostname() already returns the friendly override when set.
            "hostname": get_hostname(),
            "ip": get_lan_ip(),
            "radios_5g": radios.get("5g", []),
            "radios_2g": radios.get("2g", []),
            "macs": all_macs,
            "health_5g": health_5g
        }
        send_hmp_frame(node.raw_sock, node.udp_sock, payload, dst_mac="FF:FF:FF:FF:FF:FF", dst_ip="255.255.255.255", secret="")
        print(f"[HMP P2P] Announce sent: {primary_mac} ({payload.get('hostname')})")
        sys.stdout.flush()
    except Exception:
        pass

def handle_peer_announce(node, data, is_l2):
    """Process incoming peer announcement and update peer table."""
    if not node.neighbors_enabled:
        return
    if node.is_controller_managed():
        return
    peer_src = data.get("src_mac", "").upper()
    if not peer_src or peer_src == node.my_mac or peer_src == "00:00:00:00:00:00":
        return
    
    # Also ignore if peer_src is one of this device's own wireless MACs
    my_radios = get_wifi_radios_and_macs()
    if peer_src in [m.upper() for m in my_radios.get("all", [])]:
        return

    peer_host = data.get("hostname", "Horus-AP")
    peer_ip = data.get("ip", "")
    print(f"[HMP P2P] Discovered peer AP: {peer_src} ({peer_host}) via {'L2' if is_l2 else 'L3'}")
    sys.stdout.flush()

    peer_5g = [m.upper() for m in data.get("radios_5g", [])]
    peer_2g = [m.upper() for m in data.get("radios_2g", [])]
    peer_macs = [m.upper() for m in data.get("macs", [])]
    if peer_src and peer_src not in peer_macs:
        peer_macs.append(peer_src)
    mac_5g = (data.get("mac_5g") or "").upper()
    if mac_5g and mac_5g not in peer_macs:
        peer_macs.append(mac_5g)
    mac_lan = (data.get("mac_lan") or "").upper()
    if mac_lan and mac_lan not in peer_macs:
        peer_macs.append(mac_lan)
    
    try:
        peers_db = {}
        if os.path.exists(PEERS_FILE):
            try:
                with open(PEERS_FILE, "r") as f:
                    peers_db = json.load(f)
            except Exception:
                peers_db = {}
        
        now_t = int(time.time())
        _ttl = calculate_peer_ttl(node.neighbors_interval)
        peers_db = {k: v for k, v in peers_db.items() if (now_t - v.get("last_seen", 0)) < _ttl}
        
        local_wifi = {c['mac'].upper(): c for c in get_wireless_macs()}
        local_health = get_5g_channel_health()
        local_connected_bssid = local_health.get("connected_bssid", "").upper()
        p_health = data.get("health_5g", {})
        
        # Complementary 5G AP/STA check on the same channel
        channel_match_5g = bool(
            local_health.get("has_5g") and
            p_health.get("channel") and
            local_health.get("channel") and
            p_health.get("channel") == local_health.get("channel") and
            (
                (p_health.get("mode") == "ap" and local_health.get("mode") == "sta") or
                (p_health.get("mode") == "sta" and local_health.get("mode") == "ap")
            )
        )
        
        peer_is_wireless = (
            bool(any(pm in local_wifi for pm in peer_macs)) or
            bool(local_connected_bssid and local_connected_bssid in peer_macs) or
            channel_match_5g
        )
        
        w_info = None
        for pm in peer_macs:
            if pm in local_wifi:
                w_info = local_wifi[pm]
                break

        # Primary identifier to represent this AP
        main_ap_mac = mac_5g if mac_5g else peer_src

        for m in peer_macs:
            is_associated_wifi = peer_is_wireless or (m in local_wifi)
            
            if is_associated_wifi:
                w_iface = (w_info.get('iface', '') if w_info else '') or local_health.get('iface', '')
                if (
                    m in peer_5g or
                    m == mac_5g or
                    '5' in w_iface or
                    'phy1' in w_iface or
                    local_connected_bssid == mac_5g or
                    (local_connected_bssid and local_connected_bssid in peer_5g) or
                    channel_match_5g
                ):
                    medium = 'وايرليس 5GHz 📶'
                    medium_type = 'wireless_5g'
                else:
                    medium = 'وايرليس 2.4GHz 📶'
                    medium_type = 'wireless_2g'
                sig = w_info.get("signal") if (w_info and "signal" in w_info) else p_health.get("signal", -60)
            else:
                medium = 'كابل LAN سلكي 🔌'
                medium_type = 'lan'
                sig = p_health.get("signal", -60)

            band = "5GHz" if (m in peer_5g or m == mac_5g) else ("2.4GHz" if (m in peer_2g) else "LAN")
            peers_db[m] = {
                "hostname": peer_host,
                "ip": peer_ip,
                "band": band,
                "medium": medium,
                "medium_type": medium_type,
                "src_mac": main_ap_mac,
                "mac_5g": mac_5g,
                "mac_lan": mac_lan or peer_src,
                "noise": p_health.get("noise", -90),
                "signal": sig,
                "channel": p_health.get("channel", 36),
                "mode": p_health.get("mode", "ap"),
                "connected_bssid": p_health.get("connected_bssid", ""),
                "last_seen": now_t,
                "is_ap": True
            }
        
        tmp_p = PEERS_FILE + ".tmp"
        with open(tmp_p, "w") as f:
            json.dump(peers_db, f)
        os.replace(tmp_p, PEERS_FILE)

        # Sync to OpenWrt dnsmasq /etc/ethers and /tmp/hosts so LuCI native views resolve this AP
        sync_peer_host_hints(peers_db)
    except Exception:
        pass
