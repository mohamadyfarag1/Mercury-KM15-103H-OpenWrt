# -*- coding: utf-8 -*-
import os

ETH_P_HMP = 0x88B5
UDP_PORT = 8885

def _detect_interface():
    """Auto-detect the LAN bridge interface."""
    for name in ['br-lan', 'br0', 'br-lan.1']:
        if os.path.exists(f'/sys/class/net/{name}'):
            return name
    # Fallback: find first bridge
    try:
        for dev in os.listdir('/sys/class/net'):
            if os.path.exists(f'/sys/class/net/{dev}/bridge'):
                return dev
    except Exception:
        pass
    return 'br-lan'

INTERFACE = _detect_interface()
STATE_FILE = '/tmp/horus_network_state.json'
BAN_CMD_FILE = '/tmp/horus_ban_cmd.json'
WIFI_CMD_FILE = '/tmp/horus_wifi_cmd.json'
AP_CMD_FILE = '/tmp/horus_ap_cmd.json'

HELLO_INTERVAL = 10
TELEMETRY_INTERVAL = 5
AP_DEAD_TIMEOUT = 30
