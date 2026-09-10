# -*- coding: utf-8 -*-
"""
Horus RADIUS Sync Engine - Core Daemon & Engine Dispatcher
Orchestrates periodic UCI configuration polling, engine instantiation,
ARP & station discovery, and continuous JSON state reporting.
"""

import time

from .common import (
    get_uci,
    get_arp_table,
    get_connected_wifi_macs,
    write_json_output,
)
from .sas import SasEngine
from .dma import DmaEngine
from .adv import AdvEngine
from .icm import IcmEngine
from .um7 import Um7Engine
from .freenet import FreeNetEngine
from .mikrotik import MikrotikEngine


def get_engine(rtype, base_url, username, password, api_key=None, api_port=None):
    """Instantiates the appropriate RADIUS/RouterOS engine instance."""
    if rtype == "sas":
        return SasEngine(base_url, username, password)
    elif rtype == "dma":
        return DmaEngine(base_url, username, password, api_key)
    elif rtype == "adv":
        return AdvEngine(base_url, username, password, api_key)
    elif rtype == "icm":
        return IcmEngine(base_url, username, password, api_key)
    elif rtype == "um7":
        return Um7Engine(base_url, username, password)
    elif rtype == "freenet":
        return FreeNetEngine(base_url, username, password, api_key=api_key)
    elif rtype == "mikrotik":
        return MikrotikEngine(base_url, username, password, api_key=api_key, api_port=api_port)
    return None


def main():
    """Main daemon loop executed by /usr/bin/horus-radius.py."""
    while True:
        try:
            enabled = get_uci("enabled", "0")
            if enabled == "1":
                rtype = get_uci("radius_type", "sas")
                base_url = get_uci(f"{rtype}_base_url") or get_uci("base_url")
                username = get_uci(f"{rtype}_username") or get_uci("username")
                password = get_uci(f"{rtype}_password") or get_uci("password")
                api_key = get_uci(f"{rtype}_api_key") or get_uci("api_key")
                api_port = get_uci(f"{rtype}_api_port") or get_uci("api_port")
                interval = int(get_uci(f"{rtype}_sync_interval") or get_uci("sync_interval", "10") or 10)
                if interval < 3:
                    interval = 5

                if base_url and username:
                    mac_to_ip, ip_to_mac = get_arp_table()
                    connected_macs = get_connected_wifi_macs()

                    engine = get_engine(rtype, base_url, username, password, api_key=api_key, api_port=api_port)
                    if engine:
                        records, status = engine.sync(connected_macs, mac_to_ip, ip_to_mac)
                    else:
                        records, status = [], "disabled"

                    write_json_output(records, status=status, radius_type=rtype)
                else:
                    write_json_output([], status="disabled", radius_type=rtype)
                
                time.sleep(interval)
            else:
                write_json_output([], status="disabled", radius_type="sas")
                time.sleep(10)
        except Exception:
            try:
                write_json_output([], status="offline", radius_type=rtype)
            except NameError:
                write_json_output([], status="offline", radius_type="sas")
            time.sleep(10)
