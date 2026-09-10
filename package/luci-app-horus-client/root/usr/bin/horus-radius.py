#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
Horus Central RADIUS Sync Engine (Python 3)
Entrypoint wrapper for horus.radius package.
Maintains full backward compatibility for procd (/etc/init.d/horus_client)
and any scripts or diagnostics importing classes/functions directly.
"""

import sys
sys.path.insert(0, '/usr/lib')

from horus.radius import (
    JSON_OUT,
    TOKEN_FILE,
    decrypt_uci,
    get_uci,
    normalize_mac,
    get_arp_table,
    get_connected_wifi_macs,
    write_json_output,
    quote,
    custom_urlencode,
    http_req,
    SasEngine,
    DmaEngine,
    AdvEngine,
    IcmEngine,
    Um7Engine,
    FreeNetEngine,
    MikrotikApiClient,
    MikrotikEngine,
    parse_routeros_uptime,
    get_engine,
    main,
)

if __name__ == '__main__':
    main()
