# -*- coding: utf-8 -*-
import os
import json
import time
import subprocess
from .system import (
    get_uci, get_hostname, get_lan_ip, get_lan_netmask, get_lan_gateway,
    get_wifi_info, get_ethernet_ports, get_system_stats, get_scan_data,
    get_wireless_macs, get_wifi_radios_and_macs
)

CONTROLLER_INFO_FILE = "/tmp/horus_controller_info.json"
CONTROLLER_ALIVE_WINDOW = 60

from .logutil import get_logger
log = get_logger("horus.sat_telemetry")

def wifi_info_no_secrets():
    """Strip wifi passwords before network transmission."""
    info = get_wifi_info()
    out = []
    for w in (info or []):
        w2 = dict(w)
        w2.pop("password", None)
        out.append(w2)
    return out

def is_controller_managed(node):
    """True when this AP is adopted AND its controller is currently alive."""
    if not node.secret:
        return False
    try:
        with open(CONTROLLER_INFO_FILE, "r") as f:
            info = json.load(f)
        last = int(info.get("last_heartbeat", 0) or 0)
    except Exception:
        return False
    if last <= 0:
        return False
    return (int(time.time()) - last) < CONTROLLER_ALIVE_WINDOW

def send_hello_once(node):
    """Send Hello beacon to controller."""
    try:
        payload = {
            "type": "hello",
            "src_mac": node.my_mac,
            # get_hostname() returns the friendly override when set, so the name
            # the extension broadcasts follows the UI edit live.
            "hostname": get_hostname(),
            "ip": get_lan_ip(),
        }
        if node.secret:
            payload.update({
                "netmask": get_lan_netmask(),
                "gateway": get_lan_gateway(),
                "wifi": wifi_info_no_secrets(),
                "ports": get_ethernet_ports(),
                "stats": get_system_stats(),
                "radio_macs": get_wifi_radios_and_macs().get("all", []),
            })
            if node.controller_mac:
                payload["adopted_by"] = node.controller_mac
        node.send_to_root(payload)
    except Exception:
        pass

def send_telemetry_once(node):
    """Send full telemetry and client statistics to controller."""
    try:
        if not node.secret:
            return
        payload = {
            "type": "telemetry",
            "src_mac": node.my_mac,
            "hostname": get_hostname(),
            "ip": get_lan_ip(),
            "netmask": get_lan_netmask(),
            "gateway": get_lan_gateway(),
            "clients": get_wireless_macs(),
            "wifi": wifi_info_no_secrets(),
            "ports": get_ethernet_ports(),
            "stats": get_system_stats(),
            "radio_macs": get_wifi_radios_and_macs().get("all", []),
            "scan_data": get_scan_data()
        }
        try:
            from .integrity import telemetry_status
            payload["integrity"] = telemetry_status()
        except Exception:
            pass
        node.send_to_root(payload)
    except Exception:
        log.exception("send_telemetry_once failed")

def handle_root_heartbeat(node, data, is_l2, target_ap):
    """Process controller heartbeat, maintain adoption state and status file."""
    now_ts = int(time.time())
    if is_l2:
        node.last_l2_seen = now_ts

    root_name = data.get("root_hostname", "Controller")
    root_mac = str(data.get("src_mac", "")).upper()

    if node.secret and node.controller_mac and root_mac and root_mac != node.controller_mac:
        return

    if node.secret and not node.controller_mac and root_mac:
        node.controller_mac = root_mac
        try:
            subprocess.run(f"uci set horus_controller.main.controller_mac='{root_mac}'", shell=True)
            subprocess.run("uci commit horus_controller", shell=True)
        except Exception:
            log.exception("persisting controller_mac failed")

    configured_ip = get_uci("horus_controller.main.controller_ip", "")
    node.controller_ip = configured_ip if configured_ip else ""

    if target_ap == "ALL":
        status_str = "online"
        try:
            with open(CONTROLLER_INFO_FILE, "r") as f:
                status_str = json.load(f).get("status") or "online"
        except Exception:
            pass
    else:
        is_authorized = data.get("is_authorized", True)
        status_str = "online" if is_authorized else "awaiting_activation"

    info = {
        "status": status_str,
        "controller_ip": node.controller_ip,
        "controller_hostname": root_name,
        "controller_mac": root_mac,
        "last_heartbeat": now_ts,
        "mode": "L3 UDP Routing" if node.controller_ip else "L2 HMP Direct Mesh"
    }
    try:
        with open(CONTROLLER_INFO_FILE, "w") as f:
            json.dump(info, f)
    except Exception:
        pass
