# -*- coding: utf-8 -*-
"""
Horus RADIUS Sync Engine - DMA Radius Engine
Fetches online subscribers and batch overviews in single fast HTTP cycles,
matching subscribers against connected WiFi/ARP tables in-memory.
"""

import json

from .http import http_req, custom_urlencode
from .common import normalize_mac


class DmaEngine:
    def __init__(self, base_url, username, password, api_key):
        self.base_url = base_url.strip().rstrip("/")
        if not self.base_url.startswith("http://") and not self.base_url.startswith("https://"):
            self.base_url = "http://" + self.base_url
        if not self.base_url.endswith(".php"):
            self.url = f"{self.base_url}/user_api.php"
        else:
            self.url = self.base_url
        self.username = username
        self.password = password
        self.key = api_key or "Mohamady_Radius_2026"

    def sync(self, connected_macs, mac_to_ip, ip_to_mac):
        params = custom_urlencode({
            "key": self.key,
            "admin_user": self.username,
            "admin_pass": self.password,
            "action": "online"
        })
        full_url = f"{self.url}?{params}"
        res = http_req(full_url, timeout=5)
        if not res or not isinstance(res, dict) or "data" not in res:
            return [], "offline"
        
        online_list = res.get("data", [])
        if not isinstance(online_list, list):
            online_list = []

        # If online_list has users, fetch their balances & detailed quotas via batch_overview in 1 batch query
        usernames = [u.get("username") for u in online_list if u.get("username")]
        if usernames:
            try:
                ov_params = custom_urlencode({
                    "key": self.key,
                    "admin_user": self.username,
                    "admin_pass": self.password,
                    "action": "batch_overview",
                    "users": json.dumps(usernames)
                })
                ov_res = http_req(f"{self.url}?{ov_params}", timeout=5)
                if ov_res and isinstance(ov_res, dict) and "data" in ov_res:
                    ov_data = ov_res.get("data", {})
                    for item in online_list:
                        u_name = item.get("username")
                        if u_name and u_name in ov_data and ov_data[u_name]:
                            u_ov = ov_data[u_name]
                            if "balance" in u_ov:
                                item["balance"] = u_ov["balance"]
                            if "remaining_traffic_bytes" in u_ov and u_ov["remaining_traffic_bytes"] is not None:
                                item["remainingTrafficBytes"] = u_ov["remaining_traffic_bytes"]
            except Exception:
                pass

        online_by_mac = {}
        online_by_ip = {}
        for item in online_list:
            m = normalize_mac(item.get("mac") or item.get("normalized_mac") or item.get("callingstationid") or "")
            if m:
                online_by_mac[m] = item
            u_mac = normalize_mac(item.get("username") or "")
            if u_mac:
                online_by_mac[u_mac] = item
            ip = item.get("ip") or item.get("framedipaddress") or ""
            if ip:
                online_by_ip[ip] = item

        results = []
        for mac in connected_macs:
            ip = mac_to_ip.get(mac, "")
            user = online_by_mac.get(mac) or (online_by_ip.get(ip) if ip else None)
            if user:
                quota = user.get("remainingTrafficBytes")
                if quota is None:
                    quota = user.get("remaining_bytes") or user.get("quota") or ""

                results.append({
                    "mac": mac,
                    "name": user.get("name") or user.get("firstname") or user.get("username") or "",
                    "profile": user.get("profile_name") or user.get("profile") or user.get("srvname") or "",
                    "expiration": user.get("expiration") or "",
                    "quota": quota,
                    "balance": str(user.get("balance") or user.get("credits") or user.get("money") or "0"),
                    "loan": str(user.get("loan_balance") or user.get("loan") or ""),
                    "ip": user.get("ip") or user.get("framedipaddress") or ip,
                    "session": int(user.get("uptime") or user.get("session") or 0),
                    "username": user.get("username") or mac
                })
        return results, "online"
