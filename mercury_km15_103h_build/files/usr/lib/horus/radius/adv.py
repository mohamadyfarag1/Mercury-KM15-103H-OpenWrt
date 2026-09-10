# -*- coding: utf-8 -*-
"""
Horus RADIUS Sync Engine - ADV Radius Engine
Matches the official ADV API Documentation (v1.2.0):
- API endpoint base: <base_url>/app_ad2
- Header-based Master Key: X-Api-Key: <master_key> (from License ID in panel)
- Form-urlencoded authentication via lowercase MD5 + plaintext password
- Session token tracking via adv_auth_ad header and /check_token validation
- Bulk active query via /get_online_users with limit=5000 & multi-MAC indexing
- Direct per-MAC fallback lookup via /search_users and /get_user_by_username
"""

import re
import json
import time
import hashlib

from .http import http_req, custom_urlencode
from .common import normalize_mac


class AdvEngine:
    def __init__(self, base_url, username, password, api_key=None):
        u = (base_url or "").strip().rstrip("/")
        if not u.startswith("http://") and not u.startswith("https://"):
            u = "http://" + u
        # Strip trailing /login or /login.php if present
        u = re.sub(r'/login(\.php)?$', '', u).rstrip('/')
        # Match Flutter/API normalizeUrl: ensure /app_ad2 is present
        if not u.endswith('/app_ad2'):
            u = f"{u}/app_ad2"

        self.base_url = u
        self.username = username
        self.password = password
        # Master key (License ID). Must match License ID from ADV admin panel
        self.master_key = (api_key or "").strip() or "8610"
        self.token = ""
        self.mac_cache = {}  # mac -> (timestamp, user_data)

    def _headers(self):
        h = {
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Api-Key": self.master_key,
        }
        if self.token:
            h["adv_auth_ad"] = self.token
        return h

    def check_token(self):
        """Checks if existing session token is still valid via /check_token."""
        if not self.token:
            return False
        try:
            res = http_req(f"{self.base_url}/check_token", data="", headers=self._headers(), timeout=5)
            if res and isinstance(res, dict) and not res.get("error"):
                valid = res.get("valid")
                if valid is True or str(valid) == "1":
                    return True
        except Exception:
            pass
        return False

    def login(self):
        """Authenticates with ADV server using documented MD5 + plain password."""
        md5_pass = hashlib.md5(self.password.encode('utf-8')).hexdigest().lower()
        payload = custom_urlencode({
            "username": self.username,
            "password": md5_pass,
            "password_plain": self.password,
        })
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Api-Key": self.master_key,
        }
        res = http_req(f"{self.base_url}/login", data=payload, headers=headers, timeout=6)
        if res and isinstance(res, dict) and not res.get("error"):
            account = res.get("account") or {}
            token = account.get("api_key") or res.get("token") or (res.get("data", {}).get("token") if isinstance(res.get("data"), dict) else None)
            if token:
                self.token = str(token).strip()
                return self.token
        return None

    def get_token(self):
        if self.token and self.check_token():
            return self.token
        self.token = ""
        return self.login()

    def get_online_count(self):
        token = self.get_token()
        if not token:
            return 0
        try:
            payload = custom_urlencode({"limit": "10", "offset": "0"})
            res = http_req(f"{self.base_url}/get_online_users", data=payload, headers=self._headers(), timeout=5)
            if res and isinstance(res, dict) and not res.get("error"):
                return res.get("count", len(res.get("data") or []))
        except Exception:
            pass
        return 0

    def _index_user(self, online_by_mac, item):
        """Indexes user record under all known MAC forms and fields."""
        if not isinstance(item, dict):
            return

        # 1. Callingstationid (standard FreeRADIUS radacct attribute)
        csid = normalize_mac(item.get("callingstationid") or "")
        if csid:
            online_by_mac[csid] = item

        # 2. Single MAC
        m = normalize_mac(item.get("mac") or "")
        if m:
            online_by_mac[m] = item

        # 3. Multi-MACs field (comma-separated string or JSON array)
        macs_val = item.get("macs")
        if macs_val:
            if isinstance(macs_val, list):
                for single in macs_val:
                    norm = normalize_mac(single)
                    if norm:
                        online_by_mac[norm] = item
            elif isinstance(macs_val, str):
                if macs_val.strip().startswith("["):
                    try:
                        arr = json.loads(macs_val)
                        if isinstance(arr, list):
                            for single in arr:
                                norm = normalize_mac(single)
                                if norm:
                                    online_by_mac[norm] = item
                    except Exception:
                        pass
                for single in macs_val.split(","):
                    norm = normalize_mac(single.strip())
                    if norm:
                        online_by_mac[norm] = item

        # 4. Username if username is formatted as MAC address
        u_mac = normalize_mac(item.get("username") or "")
        if u_mac and len(u_mac) == 17:
            online_by_mac[u_mac] = item

    def _parse_user_record(self, user, mac, fallback_ip=""):
        """Extracts standard Horus subscriber metrics from ADV user object."""
        quota = user.get("remaining_traffic_bytes")
        if quota is None:
            # In ADV, av_qouta / available_qouta is in MB
            av_q = (
                user.get("av_qouta")
                or user.get("av_quota")
                or user.get("available_qouta")
                or user.get("remaining_traffic")
                or user.get("quota")
            )
            if av_q is not None:
                try:
                    quota = int(float(av_q) * 1024 * 1024)
                except (ValueError, TypeError):
                    quota = str(av_q)
            else:
                quota = ""

        balance = user.get("balance") or user.get("credit") or user.get("money") or "0"
        loan = user.get("loan_balance") or user.get("loan") or ""

        return {
            "mac": mac,
            "name": user.get("name") or user.get("firstname") or user.get("username") or "",
            "profile": user.get("profile_name") or user.get("profile") or user.get("srvname") or user.get("serv_name") or "",
            "expiration": user.get("expiration") or "",
            "quota": quota,
            "balance": str(balance),
            "loan": str(loan),
            "ip": user.get("framedipaddress") or user.get("ip") or user.get("framed_ip") or fallback_ip,
            "session": int(user.get("acctsessiontime") or user.get("uptime") or user.get("session") or 0),
            "username": user.get("username") or mac
        }

    def fetch_user_by_mac(self, mac):
        """Direct query for a single MAC via search_users and get_user_by_username."""
        if not mac:
            return None
        now = time.time()
        cached = self.mac_cache.get(mac)
        if cached:
            ts, data = cached
            # Cache positive hits for 60s, negative for 30s
            ttl = 60 if data else 30
            if now - ts < ttl:
                return data

        token = self.get_token()
        if not token:
            return None

        headers = self._headers()
        clean_mac = mac.replace(":", "").lower()

        # 1. Try search_users with MAC (colon and clean formats)
        for q in [mac, clean_mac]:
            try:
                payload = custom_urlencode({"query": q, "limit": "1"})
                res = http_req(f"{self.base_url}/search_users", data=payload, headers=headers, timeout=4)
                if res and isinstance(res, dict) and not res.get("error"):
                    data = res.get("data")
                    if isinstance(data, list) and data:
                        self.mac_cache[mac] = (now, data[0])
                        return data[0]
                    elif isinstance(data, dict) and data:
                        self.mac_cache[mac] = (now, data)
                        return data
            except Exception:
                pass

        # 2. Try get_user_by_username (hotspot username = MAC)
        for u_name in [mac, clean_mac]:
            try:
                payload = custom_urlencode({"username": u_name})
                res = http_req(f"{self.base_url}/get_user_by_username", data=payload, headers=headers, timeout=4)
                if res and isinstance(res, dict) and not res.get("error"):
                    user = res.get("data") or res.get("user") or (res if res.get("username") else None)
                    if isinstance(user, dict) and (user.get("username") or user.get("user_id")):
                        self.mac_cache[mac] = (now, user)
                        return user
            except Exception:
                pass

        self.mac_cache[mac] = (now, None)
        return None

    def sync(self, connected_macs, mac_to_ip, ip_to_mac):
        token = self.get_token()
        if not token:
            return [], "offline"

        headers = self._headers()
        # Request up to 5000 users instead of default server limit (data="")
        payload = custom_urlencode({"limit": "5000", "offset": "0"})
        res = http_req(f"{self.base_url}/get_online_users", data=payload, headers=headers, timeout=6)

        # Automatic session renewal on 401 / expired token
        if not res or not isinstance(res, dict) or res.get("error") is True:
            self.token = ""
            token = self.login()
            if not token:
                return [], "offline"
            headers = self._headers()
            res = http_req(f"{self.base_url}/get_online_users", data=payload, headers=headers, timeout=6)

        if not res or not isinstance(res, dict) or res.get("error") is True:
            return [], "offline"

        online_list = res.get("data", [])
        if not isinstance(online_list, list):
            online_list = []

        online_by_mac = {}
        online_by_ip = {}
        for item in online_list:
            if not isinstance(item, dict):
                continue
            self._index_user(online_by_mac, item)
            ip = item.get("framedipaddress") or item.get("ip") or item.get("framed_ip") or ""
            if ip:
                online_by_ip[ip] = item

        results = []
        for mac in connected_macs:
            ip = mac_to_ip.get(mac, "")
            user = online_by_mac.get(mac) or (online_by_ip.get(ip) if ip else None)

            # Fallback: if connected MAC is not found in online active list, query ADV directly by MAC
            if not user:
                user = self.fetch_user_by_mac(mac)

            if user:
                record = self._parse_user_record(user, mac, fallback_ip=ip)
                results.append(record)

        return results, "online"
