# -*- coding: utf-8 -*-
"""
Horus RADIUS Sync Engine - ICM Radius Engine
Performs single bulk fetch of subscriber lists with session details,
and matches subscribers against connected AP clients in-memory.
"""

from .http import http_req, custom_urlencode
from .common import normalize_mac


class IcmEngine:
    DEFAULT_KEY = "7f3a9c5e2d8b4f6a1e7c3b9d5f2a8e4c"

    def __init__(self, base_url, username, password, api_key=None):
        u = base_url.strip().rstrip("/")
        if not u.startswith("http://") and not u.startswith("https://"):
            u = "https://" + u
        if "/api/users/list" in u:
            if not u.endswith(".php"):
                self.url = u + "/index.php"
            else:
                self.url = u
        else:
            self.url = f"{u}/api/users/list/index.php"
        self.username = username
        self.password = password
        self.key = api_key or self.DEFAULT_KEY

    def sync(self, connected_macs, mac_to_ip, ip_to_mac):
        params = custom_urlencode({
            "username": self.username,
            "password": self.password,
            "key": self.key,
            "include_sessions": "1",
            "limit": "2000",
        })
        res = http_req(f"{self.url}?{params}", timeout=8)
        if not res or not isinstance(res, dict) or res.get("status") != "success":
            return [], "offline"

        data = res.get("data") or {}
        subs = data.get("subscribers")
        if not isinstance(subs, list):
            return [], "offline"

        by_mac = {}
        by_ip = {}
        for item in subs:
            sess = item.get("current_session") or {}
            m = normalize_mac(sess.get("mac_address") or item.get("mac") or "")
            if not m:
                u_m = normalize_mac(item.get("username") or "")
                if u_m and len(u_m) == 17:
                    m = u_m

            ip = sess.get("private_ip") or item.get("ip") or ""

            status = item.get("status") or {}
            is_on = status.get("is_online", False)

            if m:
                if m not in by_mac or is_on:
                    by_mac[m] = item
            if ip:
                if ip not in by_ip or is_on:
                    by_ip[ip] = item

        results = []
        for mac in connected_macs:
            ip = mac_to_ip.get(mac, "")
            item = by_mac.get(mac) or (by_ip.get(ip) if ip else None)
            if not item:
                continue

            sess = item.get("current_session") or {}
            quota = item.get("quota") or {}
            balance = item.get("balance") or {}
            expiration = item.get("expiration") or {}
            profile = item.get("profile") or {}

            # Calculate remaining quota in bytes
            remaining_bytes = ""
            if quota:
                rem = quota.get("remaining_gb")
                tot = quota.get("total_gb")
                used = quota.get("used_gb")

                val = rem if rem is not None else (float(tot) - float(used or 0) if tot is not None else None)
                if val is not None:
                    try:
                        v_flt = float(val)
                        if v_flt > 100000:
                            # ICM expresses this quota in KB
                            remaining_bytes = int(v_flt * 1024)
                        elif v_flt >= 0:
                            # ICM expresses this quota in GB
                            remaining_bytes = int(v_flt * 1024 * 1024 * 1024)
                        elif v_flt < 0:
                            remaining_bytes = -1
                    except (TypeError, ValueError):
                        pass

            bal_val = balance.get("current")
            if bal_val is None:
                bal_val = balance.get("credit", "0")

            disp_name = item.get("full_name") or item.get("name") or item.get("username") or ""

            results.append({
                "mac": mac,
                "name": disp_name,
                "profile": profile.get("name") or "",
                "expiration": expiration.get("expire_date") or "",
                "quota": remaining_bytes,
                "balance": str(bal_val) if bal_val is not None else "0",
                "loan": "",
                "ip": sess.get("private_ip") or ip,
                "session": int(sess.get("duration_seconds") or 0),
                "username": item.get("username") or mac
            })
        return results, "online"
