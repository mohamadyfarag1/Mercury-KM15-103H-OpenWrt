# -*- coding: utf-8 -*-
"""
Horus RADIUS Sync Engine - System & Network Utilities
Provides ARP inspection, connected WiFi station discovery, MAC normalization,
UCI config extraction, and atomic JSON state dumping.
"""

import os
import re
import json
import time
import subprocess

JSON_OUT = "/tmp/horus_radius.json"


def decrypt_uci(val):
    if val and val.startswith("enc3_"):
        try:
            import base64
            res = base64.b64decode(val[5:])
            key = b"horus_radius_2026"
            return bytes([b ^ key[i % len(key)] for i, b in enumerate(res)]).decode('utf-8')
        except Exception:
            pass
    return val


def get_uci(option, default=""):
    try:
        out = subprocess.check_output(f"uci -q get horus_controller.main.{option}", shell=True, text=True).strip()
        if out:
            return decrypt_uci(out)
        return default
    except Exception:
        return default


def normalize_mac(mac):
    if not mac:
        return ""
    clean = re.sub(r'[^A-Fa-f0-9]', '', str(mac)).upper()
    if len(clean) == 12:
        return ":".join(clean[i:i+2] for i in range(0, 12, 2))
    return mac.upper()


def get_arp_table():
    mac_to_ip = {}
    ip_to_mac = {}
    
    if os.path.exists("/proc/net/arp"):
        try:
            with open("/proc/net/arp", "r", encoding="utf-8", errors="ignore") as f:
                for line in f.readlines()[1:]:
                    parts = line.split()
                    if len(parts) >= 4:
                        ip = parts[0]
                        mac = normalize_mac(parts[3])
                        if mac and mac != "00:00:00:00:00:00":
                            mac_to_ip[mac] = ip
                            ip_to_mac[ip] = mac
        except Exception:
            pass

    try:
        out = subprocess.check_output("ip neigh show", shell=True, text=True)
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 5 and "lladdr" in parts:
                idx = parts.index("lladdr")
                if idx + 1 < len(parts):
                    ip = parts[0]
                    mac = normalize_mac(parts[idx + 1])
                    if mac:
                        mac_to_ip[mac] = ip
                        ip_to_mac[ip] = mac
    except Exception:
        pass

    return mac_to_ip, ip_to_mac


def get_connected_wifi_macs():
    macs = set()
    
    try:
        out = subprocess.check_output("iwinfo | grep -E '^[a-zA-Z0-9_-]+'", shell=True, text=True)
        for line in out.splitlines():
            iface = line.split()[0]
            try:
                assoc = subprocess.check_output(f"iwinfo {iface} assoclist", shell=True, text=True)
                for m in re.findall(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', assoc):
                    macs.add(normalize_mac(m))
            except Exception:
                pass
    except Exception:
        pass

    try:
        out = subprocess.check_output("iw dev", shell=True, text=True)
        for line in out.splitlines():
            if line.strip().startswith("Interface"):
                iface = line.split()[1]
                try:
                    dump = subprocess.check_output(f"iw dev {iface} station dump", shell=True, text=True)
                    for m in re.findall(r'Station\s+((?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2})', dump):
                        macs.add(normalize_mac(m))
                except Exception:
                    pass
    except Exception:
        pass

    try:
        if os.path.exists("/tmp/horus_network_state.json"):
            with open("/tmp/horus_network_state.json", "r") as f:
                state = json.load(f)
                clients = state.get("clients", {})
                for m in clients.keys():
                    macs.add(normalize_mac(m))
    except Exception:
        pass

    return list(macs)


def write_json_output(records, status="online", radius_type="sas"):
    try:
        tmp_file = "/tmp/horus_radius.tmp"
        output_payload = {
            "status": status,
            "radius_type": radius_type,
            "timestamp": int(time.time()),
            "count": len(records),
            "data": records
        }
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(output_payload, f, ensure_ascii=False)
        os.replace(tmp_file, JSON_OUT)
    except Exception:
        pass
