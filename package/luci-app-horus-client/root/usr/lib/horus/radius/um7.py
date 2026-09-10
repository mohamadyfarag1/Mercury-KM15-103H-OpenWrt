# -*- coding: utf-8 -*-
"""
Horus RADIUS Sync Engine - MikroTik User Manager 7 Engine
Connects to RouterOS v7 native REST API with Basic Auth and verify=False
(accommodating self-signed router certs), filtering active sessions client-side.
"""

import base64

from .http import http_req
from .common import normalize_mac
from .mikrotik import parse_routeros_uptime


class Um7Engine:
    def __init__(self, base_url, username, password):
        self.base_url = base_url.strip().rstrip("/")
        if not self.base_url.startswith("http://") and not self.base_url.startswith("https://"):
            self.base_url = "https://" + self.base_url
        self.username = username
        self.password = password

    def sync(self, connected_macs, mac_to_ip, ip_to_mac):
        auth = base64.b64encode(f"{self.username}:{self.password}".encode("utf-8")).decode("ascii")
        headers = {"Authorization": f"Basic {auth}"}
        # RouterOS's own REST API almost always runs on a self-signed cert out
        # of the box -- verify=False here is deliberate (see http_req), unlike
        # every other engine which keeps full certificate validation.
        res = http_req(f"{self.base_url}/rest/user-manager/session", headers=headers, timeout=6, verify=False)
        if not isinstance(res, list):
            return [], "offline"

        online_by_mac = {}
        online_by_ip = {}
        for s in res:
            active = s.get("active")
            if not (active is True or active == 1 or str(active).lower() == "true"):
                continue
            m = normalize_mac(s.get("mac-address") or "")
            if m:
                online_by_mac[m] = s
            ip = s.get("ip-address") or ""
            if ip:
                online_by_ip[ip] = s

        results = []
        for mac in connected_macs:
            ip = mac_to_ip.get(mac, "")
            s = online_by_mac.get(mac) or (online_by_ip.get(ip) if ip else None)
            if not s:
                continue

            username = s.get("user") or mac
            results.append({
                "mac": mac,
                "name": username,
                # RouterOS User Manager has no native balance/quota wallet the
                # way SAS/DMA do -- profiles are time/traffic-limited at the
                # router level, not tracked here. Left blank rather than
                # guessed.
                "profile": "",
                "expiration": "",
                "quota": "",
                "balance": "",
                "loan": "",
                "ip": s.get("ip-address") or ip,
                "session": parse_routeros_uptime(s.get("uptime")),
                "username": username
            })
        return results, "online"
