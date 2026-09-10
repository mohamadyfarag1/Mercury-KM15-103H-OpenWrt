# -*- coding: utf-8 -*-
import os
import subprocess
import time
from .config import INTERFACE
from .sys_utils import format_speed, format_bytes
from .sys_wifi import get_wireless_macs

PREV_SYS_NET = {"rx": 0, "tx": 0, "ts": 0}

def get_my_mac():
    # 1. Try detected primary interface and common candidates
    for iface in [INTERFACE, 'br-lan', 'eth0', 'eth1', 'wlan0', 'wlan1']:
        try:
            p = f"/sys/class/net/{iface}/address"
            if os.path.exists(p):
                with open(p, "r") as f:
                    mac = f.read().strip().upper()
                if mac and mac != "00:00:00:00:00:00" and len(mac) == 17:
                    return mac
        except Exception:
            pass
    # 2. Search any active interface in /sys/class/net
    try:
        for dev in os.listdir('/sys/class/net'):
            if dev == 'lo' or dev.startswith(('dummy', 'ifb', 'tun', 'tap', 'wg', 'sit', 'ip6')):
                continue
            try:
                with open(f"/sys/class/net/{dev}/address", "r") as f:
                    mac = f.read().strip().upper()
                if mac and mac != "00:00:00:00:00:00" and len(mac) == 17:
                    return mac
            except Exception:
                pass
    except Exception:
        pass
    return "00:00:00:00:00:00"

def get_lan_ip():
    try:
        out = subprocess.check_output("uci -q get network.lan.ipaddr", shell=True, text=True).strip()
        if not out or out == "0.0.0.0":
            out = subprocess.check_output("ip -4 addr show br-lan | grep -o 'inet [0-9.]*' | cut -d' ' -f2", shell=True, text=True).strip()
        return out if out else "0.0.0.0"
    except Exception:
        return "0.0.0.0"

def get_lan_netmask():
    try:
        out = subprocess.check_output("uci -q get network.lan.netmask", shell=True, text=True).strip()
        return out if out else "255.255.255.0"
    except Exception:
        return "255.255.255.0"

def get_lan_gateway():
    try:
        out = subprocess.check_output("uci -q get network.lan.gateway", shell=True, text=True).strip()
        if out:
            return out
        # Fallback: Read actual kernel default gateway
        out = subprocess.check_output("ip route | grep default | awk '{print $3}' | head -n1", shell=True, text=True).strip()
        return out if out else ""
    except Exception:
        return ""

def get_hostname():
    try:
        with open("/proc/sys/kernel/hostname", "rb") as f:
            raw = f.read().strip()
            if raw:
                try:
                    return raw.decode("utf-8")
                except Exception:
                    return raw.decode("latin1", errors="replace")
    except Exception:
        pass
    try:
        out = subprocess.check_output("uci -q get system.@system[0].hostname", shell=True)
        if out:
            return out.decode("utf-8", errors="replace").strip()
    except Exception:
        pass
    return "Horus-AP"

def get_system_stats():
    global PREV_SYS_NET
    now = time.time()
    cpu_load = "0.0"
    cpu_temp = "-"
    mem_used_pct = 0
    rx_speed_bps = 0
    tx_speed_bps = 0
    total_rx = 0
    total_tx = 0
    cpu_model = "Unknown"
    flash_total = "Unknown"
    
    # 1. Device Model & CPU Model
    try:
        if os.path.exists("/tmp/sysinfo/model"):
            with open("/tmp/sysinfo/model", "r") as f:
                cpu_model = f.read().strip()
        elif os.path.exists("/proc/device-tree/model"):
            with open("/proc/device-tree/model", "r") as f:
                cpu_model = f.read().strip().replace('\x00', '')
        if not cpu_model or cpu_model == "Unknown" or "Generic" in cpu_model:
            with open("/proc/cpuinfo", "r") as f:
                for line in f:
                    if "model name" in line.lower() or "system type" in line.lower() or "machine" in line.lower():
                        cpu_model = line.split(":", 1)[1].strip()
                        break
    except Exception:
        pass
    
    # 2. Flash Size & Usage
    try:
        out = subprocess.check_output("df -h /overlay 2>/dev/null || df -h /", shell=True, text=True)
        lines = out.strip().splitlines()
        if len(lines) > 1:
            parts = lines[1].split()
            if len(parts) >= 4:
                flash_total = f"{parts[1]} (متاح {parts[3]})"
    except Exception:
        pass

    # 3. CPU Load
    try:
        with open("/proc/loadavg", "r") as f:
            cpu_load = f.read().split()[0]
    except Exception:
        pass

    # 4. CPU / SoC Temperature
    try:
        thermal_files = [
            "/sys/class/thermal/thermal_zone0/temp",
            "/sys/class/thermal/thermal_zone1/temp",
            "/sys/class/hwmon/hwmon0/temp1_input",
            "/sys/class/hwmon/hwmon1/temp1_input",
            "/sys/class/hwmon/hwmon0/device/temp1_input"
        ]
        for z in thermal_files:
            if os.path.exists(z):
                with open(z, "r") as f:
                    raw_val = f.read().strip()
                    if raw_val.isdigit():
                        val = int(raw_val)
                        if val > 1000:
                            cpu_temp = f"{val / 1000:.0f}°C"
                        else:
                            cpu_temp = f"{val}°C"
                        break
    except Exception:
        pass

    # 5. RAM Usage
    try:
        mem_total = 0
        mem_free = 0
        mem_avail = 0
        with open("/proc/meminfo", "r") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    mem_total = int(line.split()[1])
                elif line.startswith("MemAvailable:"):
                    mem_avail = int(line.split()[1])
                elif line.startswith("MemFree:") and mem_avail == 0:
                    mem_free = int(line.split()[1])
        if mem_avail > 0 and mem_total > 0:
            mem_used_pct = int(((mem_total - mem_avail) / mem_total) * 100)
        elif mem_free > 0 and mem_total > 0:
            mem_used_pct = int(((mem_total - mem_free) / mem_total) * 100)
    except Exception:
        pass

    # 6. Bandwidth Throughput across physical/wireless interfaces
    try:
        total_rx = 0
        total_tx = 0
        brif_path = f"/sys/class/net/{INTERFACE}/brif"
        devs_to_check = []
        if os.path.exists(brif_path):
            devs_to_check = [d for d in os.listdir(brif_path) if d.startswith(('wlan', 'ath', 'ra', 'phy', 'lan', 'eth'))]
        if not devs_to_check:
            devs_to_check = [d for d in os.listdir("/sys/class/net") if d.startswith(('wlan', 'ath', 'ra', 'phy', 'lan'))]
        
        for dev in devs_to_check:
            rx_p = f"/sys/class/net/{dev}/statistics/rx_bytes"
            tx_p = f"/sys/class/net/{dev}/statistics/tx_bytes"
            if os.path.exists(rx_p) and os.path.exists(tx_p):
                with open(rx_p, "r") as f: total_rx += int(f.read().strip())
                with open(tx_p, "r") as f: total_tx += int(f.read().strip())
        
        if total_rx == 0 and total_tx == 0:
            rx_p = f"/sys/class/net/{INTERFACE}/statistics/rx_bytes"
            tx_p = f"/sys/class/net/{INTERFACE}/statistics/tx_bytes"
            if os.path.exists(rx_p) and os.path.exists(tx_p):
                with open(rx_p, "r") as f: total_rx = int(f.read().strip())
                with open(tx_p, "r") as f: total_tx = int(f.read().strip())

        if PREV_SYS_NET["ts"] > 0:
            dt = now - PREV_SYS_NET["ts"]
            if dt > 0.5:
                rx_speed_bps = max(0, total_rx - PREV_SYS_NET["rx"]) * 8 / dt
                tx_speed_bps = max(0, total_tx - PREV_SYS_NET["tx"]) * 8 / dt
        PREV_SYS_NET = {"rx": total_rx, "tx": total_tx, "ts": now}
    except Exception:
        pass

    # 7. CPU Architecture
    cpu_arch = "-"
    try:
        with open("/etc/openwrt_release", "r") as f:
            for line in f:
                if "DISTRIB_ARCH" in line:
                    cpu_arch = line.split("=")[1].strip().strip("'").strip('"')
                    break
    except Exception:
        pass

    # 8. Flash State
    flash_state = "-"
    try:
        out = subprocess.check_output("df -h /overlay 2>/dev/null || df -h /", shell=True, text=True)
        lines = out.strip().splitlines()
        if len(lines) > 1:
            parts = lines[1].split()
            if len(parts) >= 5:
                flash_state = parts[3] + " Free / " + parts[1] + " Total"
    except Exception:
        pass

    return {
        "cpu_arch": cpu_arch,
        "cpu_model": cpu_model,
        "flash_state": flash_state,
        "flash_total": flash_total,
        "cpu_load": cpu_load,
        "cpu_temp": cpu_temp,
        "mem_pct": mem_used_pct,
        "rx_speed": format_speed(rx_speed_bps),
        "tx_speed": format_speed(tx_speed_bps),
        "rx_speed_bps": int(rx_speed_bps),
        "tx_speed_bps": int(tx_speed_bps),
        "total_rx": format_bytes(total_rx),
        "total_tx": format_bytes(total_tx)
    }

def get_ethernet_ports():
    ports = []
    try:
        arp_map = {}
        try:
            with open("/proc/net/arp", "r") as f:
                for line in f.readlines()[1:]:
                    parts = line.split()
                    if len(parts) >= 6:
                        ip_addr, mac_addr = parts[0], parts[3].upper()
                        if mac_addr != "00:00:00:00:00:00":
                            arp_map[mac_addr] = ip_addr
        except Exception:
            pass

        wireless_macs = set()
        try:
            for wmac_info in get_wireless_macs():
                wireless_macs.add(wmac_info.get("mac", "").upper())
        except Exception:
            pass

        # Legacy swconfig/bridge-utils path: port numbers via brctl (kernel 5.4,
        # OpenWrt <=21.02). brctl is absent on modern DSA builds (kernel 5.15/6.x),
        # so this is best-effort and complemented by the `bridge fdb` map below.
        port_macs = {}
        try:
            out = subprocess.check_output("brctl showmacs br-lan 2>/dev/null", shell=True, text=True)
            for line in out.splitlines()[1:]:
                parts = line.split()
                if len(parts) >= 3 and parts[2] == "no":
                    p_num = parts[0]
                    cmac = parts[1].upper()
                    if cmac not in wireless_macs:
                        if p_num not in port_macs: port_macs[p_num] = []
                        port_macs[p_num].append(cmac)
        except Exception:
            pass

        # Modern path (kernel 5.15+/DSA): `bridge fdb show` maps each learned
        # client MAC to the physical netdev it lives behind (e.g. lan1, lan2),
        # which is exactly how DSA exposes per-port members. Works on old kernels
        # too, so it is a universal fallback for brctl.
        fdb_by_dev = {}
        try:
            out = subprocess.check_output("bridge fdb show 2>/dev/null", shell=True, text=True)
            for line in out.splitlines():
                low = line.lower()
                if 'permanent' in low or 'self' in low:
                    continue
                parts = line.split()
                if len(parts) < 3 or parts[1] != 'dev':
                    continue
                cmac = parts[0].upper()
                dev = parts[2]
                if len(cmac) != 17 or cmac.count(':') != 5:
                    continue
                if cmac in wireless_macs:
                    continue
                try:
                    if int(cmac[:2], 16) & 1:  # skip multicast/broadcast
                        continue
                except ValueError:
                    continue
                fdb_by_dev.setdefault(dev, [])
                if cmac not in fdb_by_dev[dev]:
                    fdb_by_dev[dev].append(cmac)
        except Exception:
            pass

        has_dsa_ports = any(os.path.exists(f"/sys/class/net/{x}") for x in ['lan1', 'lan2', 'lan3', 'lan4', 'wan'])
        candidate_ports = []
        for p in ['lan1', 'lan2', 'lan3', 'lan4', 'lan', 'wan', 'eth0', 'eth1', 'eth2', 'eth3', 'ge0', 'ge1']:
            if has_dsa_ports and p in ['eth0', 'eth1']:
                continue
            if os.path.exists(f"/sys/class/net/{p}") and p not in candidate_ports:
                candidate_ports.append(p)
        try:
            for iface in sorted(os.listdir("/sys/class/net")):
                if iface in candidate_ports: continue
                if has_dsa_ports and iface in ['eth0', 'eth1']: continue
                if iface in ['lo', 'br-lan', 'docker0'] or iface.startswith(('phy', 'wlan', 'ath', 'mon', 'gre', 'tun', 'tap', 'wg', 'ppp', 'ifb')):
                    continue
                if not os.path.exists(f"/sys/class/net/{iface}/phy80211") and not os.path.exists(f"/sys/class/net/{iface}/wireless"):
                    candidate_ports.append(iface)
        except Exception:
            pass

        def _fmt_bytes(b):
            if not b or b <= 0: return "0 B"
            if b >= 1073741824: return f"{b/1073741824:.1f} GiB"
            if b >= 1048576: return f"{b/1048576:.1f} MiB"
            if b >= 1024: return f"{b/1024:.1f} KiB"
            return f"{b} B"

        for p in candidate_ports:
            p_path = f"/sys/class/net/{p}"
            if os.path.exists(p_path):
                oper = "down"
                carrier = 0
                flags_val = 0
                speed = 0
                duplex = "full"
                rx_bytes = 0
                tx_bytes = 0
                try:
                    with open(f"{p_path}/operstate", "r") as f:
                        oper = f.read().strip()
                except Exception:
                    pass
                try:
                    with open(f"{p_path}/carrier", "r") as f:
                        carrier = int(f.read().strip())
                except Exception:
                    pass
                try:
                    with open(f"{p_path}/flags", "r") as f:
                        flags_val = int(f.read().strip(), 16)
                except Exception:
                    pass
                try:
                    with open(f"{p_path}/speed", "r") as f:
                        speed = int(f.read().strip())
                except Exception:
                    pass
                try:
                    with open(f"{p_path}/duplex", "r") as f:
                        duplex = f.read().strip()
                except Exception:
                    pass
                try:
                    with open(f"{p_path}/statistics/rx_bytes", "r") as f:
                        rx_bytes = int(f.read().strip())
                except Exception:
                    pass
                try:
                    with open(f"{p_path}/statistics/tx_bytes", "r") as f:
                        tx_bytes = int(f.read().strip())
                except Exception:
                    pass
                
                is_admin_enabled = bool(flags_val & 1) if flags_val > 0 else (oper != "down")
                is_link_up = (carrier == 1) and (oper == "up")

                attached_clients = []
                if is_link_up:
                    seen_client_macs = set()
                    p_num = p.replace('lan', '')
                    if p_num in port_macs:
                        for cmac in port_macs[p_num]:
                            if cmac in seen_client_macs:
                                continue
                            seen_client_macs.add(cmac)
                            attached_clients.append({
                                "mac": cmac,
                                "ip": arp_map.get(cmac, "")
                            })
                    for cmac in fdb_by_dev.get(p, []):
                        if cmac in seen_client_macs:
                            continue
                        seen_client_macs.add(cmac)
                        attached_clients.append({
                            "mac": cmac,
                            "ip": arp_map.get(cmac, "")
                        })

                if not is_admin_enabled:
                    speed_str = "معطل برمجياً"
                    status_label = "معطل"
                elif is_link_up:
                    speed_str = f"{speed}M" if speed > 0 else "متصل"
                    status_label = "متصل"
                else:
                    speed_str = "no link"
                    status_label = "مفعل - لا يوجد كابل"

                ports.append({
                    "port": p,
                    "label": p.lower(),
                    "state": oper,
                    "is_enabled": is_admin_enabled,
                    "is_up": is_link_up,
                    "carrier": carrier,
                    "speed": speed if is_link_up else 0,
                    "speed_str": speed_str,
                    "status_label": status_label,
                    "rx_bytes": rx_bytes,
                    "tx_bytes": tx_bytes,
                    "rx_str": _fmt_bytes(rx_bytes),
                    "tx_str": _fmt_bytes(tx_bytes),
                    "clients": attached_clients
                })
    except Exception:
        pass
    return ports
