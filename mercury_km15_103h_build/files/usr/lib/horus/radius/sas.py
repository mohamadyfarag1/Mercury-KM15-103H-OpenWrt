# -*- coding: utf-8 -*-
"""
Horus RADIUS Sync Engine - SAS 4 Engine
Handles authentication token lifecycle, AES-256-CBC encryption,
overview balance/quota discovery, and concurrent multi-MAC sync.
"""

import os
import json
import time
import subprocess
import threading

from .http import http_req

TOKEN_FILE = "/tmp/sas_token.txt"


class SasEngine:
    KEY = "abcdefghijuklmno0123456789012345"

    def __init__(self, base_url, username, password):
        self.base_url = base_url.strip().rstrip("/")
        if not self.base_url.startswith("http://") and not self.base_url.startswith("https://"):
            self.base_url = "http://" + self.base_url
        self.username = username
        self.password = password
        self.token = ""
        self.user_cache = {}

        u = self.base_url
        if u.endswith("/api") or u.endswith("/api/"):
            self.login_url = u.rstrip("/") + "/login"
        elif "/api/" in u:
            self.login_url = u
        else:
            self.login_url = f"{u}/admin/api/index.php/api/login"
        
        self.online_url = self.login_url.replace("/login", "/index/online")
        self.user_url = self.login_url.replace("/login", "/index/user")
        self.overview_base_url = self.login_url.replace("/login", "/user/overview")

    def _encrypt(self, plain_text):
        try:
            cmd = f"printf '%s' '{plain_text}' | openssl enc -aes-256-cbc -md md5 -a -A -k '{self.KEY}'"
            out = subprocess.check_output(cmd, shell=True, text=True).strip()
            return out
        except Exception:
            return None

    def get_token(self, force_refresh=False):
        if self.token and not force_refresh:
            return self.token
        
        if not force_refresh and os.path.exists(TOKEN_FILE):
            try:
                with open(TOKEN_FILE, "r") as f:
                    t = f.read().strip()
                    if t:
                        self.token = t
                        return self.token
            except Exception:
                pass

        payload_plain = json.dumps({"username": self.username, "password": self.password})
        enc = self._encrypt(payload_plain)
        
        resp = None
        if enc:
            resp = http_req(self.login_url, {"payload": enc}, timeout=5, verify=False)
        if not resp or not resp.get("status"):
            resp = http_req(self.login_url, {"username": self.username, "password": self.password}, timeout=5, verify=False)

        if resp:
            token = resp.get("token") or (resp.get("data") and resp.get("data", {}).get("token"))
            if token:
                self.token = token
                try:
                    with open(TOKEN_FILE, "w") as f:
                        f.write(token)
                except Exception:
                    pass
                return token

        return None

    def fetch_online_bulk(self, token):
        payload = {"count": 1000}
        headers = {"Authorization": f"Bearer {token}"}
        
        enc = self._encrypt(json.dumps(payload))
        if enc:
            res = http_req(self.online_url, {"payload": enc}, headers=headers, timeout=6, verify=False)
            if res and res.get("status") in [True, "success", 200, "200"]:
                return res.get("data") or [], True
        return [], False
        
    def fetch_user_info_for_mac(self, mac, token):
        headers = {"Authorization": f"Bearer {token}"}
        
        user_data = None
        uid = ""
        name = ""
        profile = ""
        expiration = ""
        ip = ""
        session = 0
        quota = ""
        balance = ""
        loan = ""
        uname = mac
        
        # 1. Search in /index/online
        payload_online = {"count": 1, "search": mac}
        enc_online = self._encrypt(json.dumps(payload_online))
        if enc_online:
            res = http_req(self.online_url, {"payload": enc_online}, headers=headers, timeout=5)
            if res and isinstance(res, dict) and res.get("data") and len(res["data"]) > 0:
                user_data = res["data"][0]
                ip = user_data.get("framedipaddress") or ""
                session = user_data.get("acctsessiontime") or 0
                uname = user_data.get("username") or mac
                
                ud = user_data.get("user_details") or {}
                # Do NOT use user_data['id'] as uid because it is radacctid!
                uid = ud.get("id", "")
                name = (ud.get("firstname", "") + " " + (ud.get("lastname", "") or "")).strip()
                profile = user_data.get("user_profile_name", "") or ud.get("profile_details", {}).get("name", "")
                expiration = ud.get("expiration", "")
                balance = ud.get("balance", "")
                loan = ud.get("loan_balance", "")

        # 2. If no valid user ID or missing details, search in /index/user
        if not uid or str(uid) == "null" or not name:
            payload_user = {"count": 1, "search": mac}
            enc_user = self._encrypt(json.dumps(payload_user))
            if enc_user:
                res = http_req(self.user_url, {"payload": enc_user}, headers=headers, timeout=5)
                if res and isinstance(res, dict) and res.get("data") and len(res["data"]) > 0:
                    ud = res["data"][0]
                    if ud:
                        uid = ud.get("id", "")
                        if not uname or uname == mac:
                            uname = ud.get("username", mac)
                        if not name:
                            name = (ud.get("firstname", "") + " " + (ud.get("lastname", "") or "")).strip() or ud.get("username", "")
                        if not profile:
                            prof_det = ud.get("profile_details") or {}
                            profile = prof_det.get("name", "")
                        if not expiration:
                            expiration = ud.get("expiration", "")
                        if not balance:
                            balance = ud.get("balance", "")
                        if not loan:
                            loan = ud.get("loan_balance", "")

        # 3. If still no UID, try lowercase mac in /index/user
        if not uid and mac != mac.lower():
            payload_user = {"count": 1, "search": mac.lower()}
            enc_user = self._encrypt(json.dumps(payload_user))
            if enc_user:
                res = http_req(self.user_url, {"payload": enc_user}, headers=headers, timeout=5)
                if res and isinstance(res, dict) and res.get("data") and len(res["data"]) > 0:
                    ud = res["data"][0]
                    if ud:
                        uid = ud.get("id", "")
                        if not uname or uname == mac:
                            uname = ud.get("username", mac)
                        if not name:
                            name = (ud.get("firstname", "") + " " + (ud.get("lastname", "") or "")).strip() or ud.get("username", "")
                        if not profile:
                            prof_det = ud.get("profile_details") or {}
                            profile = prof_det.get("name", "")
                        if not expiration:
                            expiration = ud.get("expiration", "")
                        if not balance:
                            balance = ud.get("balance", "")
                        if not loan:
                            loan = ud.get("loan_balance", "")

        # 4. Fetch overview (for real-time remaining quota & balance)
        if uid and str(uid) != "null":
            ov_url = f"{self.overview_base_url}/{uid}"
            res = http_req(ov_url, headers=headers, timeout=5)
            if res and isinstance(res, dict) and res.get("data"):
                od = res.get("data") or {}
                quota = od.get("remaining_rxtx", "") or quota
                if not name:
                    name = (od.get("firstname", "") + " " + (od.get("lastname", "") or "")).strip() or od.get("username", "")
                if not profile:
                    profile = od.get("profile_name", "")
                if not expiration:
                    expiration = od.get("expiration", "")
                if not balance or balance == "0.00" or balance == 0:
                    balance = od.get("balance", balance)
                if not loan:
                    loan = od.get("loan_balance", loan)

        if not name and not profile and not ip and not uid:
            return None
            
        return {
            "mac": mac,
            "name": name or uname,
            "profile": profile,
            "expiration": expiration,
            "quota": quota,
            "balance": str(balance) if (balance is not None and balance != "") else "0.00",
            "loan": str(loan) if loan is not None else "",
            "ip": ip,
            "session": session,
            "username": uname
        }

    def sync(self, connected_macs, mac_to_ip, ip_to_mac):
        token = self.get_token()
        if not token:
            token = self.get_token(force_refresh=True)
            if not token:
                return [], "offline"

        results = []
        lock = threading.Lock()

        def _process_mac(mac):
            try:
                res = self.fetch_user_info_for_mac(mac, token)
                if res:
                    self.user_cache[mac] = {'data': res, 'ts': time.time()}
                    with lock:
                        results.append(res)
                elif mac in self.user_cache and (time.time() - self.user_cache[mac]['ts']) < 180:
                    with lock:
                        results.append(self.user_cache[mac]['data'])
            except Exception:
                if mac in self.user_cache and (time.time() - self.user_cache[mac]['ts']) < 180:
                    with lock:
                        results.append(self.user_cache[mac]['data'])

        threads = []
        for mac in connected_macs:
            t = threading.Thread(target=_process_mac, args=(mac,))
            threads.append(t)
            t.start()
            if len(threads) >= 5:
                for t in threads:
                    t.join()
                threads = []

        for t in threads:
            t.join()

        for r in results:
            r.pop("uid", None)

        return results, "online"
