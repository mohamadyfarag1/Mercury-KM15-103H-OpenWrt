# -*- coding: utf-8 -*-
"""
Horus RADIUS Sync Engine - Free Net Radius Engine
Handles Bearer token lifecycle, subscriber lookups by MAC/IP,
quota/balance extraction, and concurrent multi-MAC sync for Free Net ISP System.
"""

import os
import json
import time
import threading

from .http import http_req, quote
from .common import normalize_mac

TOKEN_FILE = "/tmp/freenet_token.txt"


class FreeNetEngine:
    def __init__(self, base_url, username, password, api_key=None):
        self.base_url = (base_url or "").strip().rstrip("/")
        if not self.base_url.startswith("http://") and not self.base_url.startswith("https://"):
            self.base_url = "http://" + self.base_url
        self.username = username or ""
        self.password = password or ""
        self.api_key = api_key or ""
        self.token = ""
        self.user_cache = {}

        # URL normalization
        u = self.base_url.rstrip("/")
        if u.endswith("/api/manager"):
            self.api_root = u
        elif u.endswith("/api"):
            self.api_root = f"{u}/manager"
        else:
            self.api_root = f"{u}/api/manager"

        self.login_url = f"{self.api_root}/login"
        self.subscribers_url = f"{self.api_root}/subscribers"

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

        payload = {
            "login": self.username,
            "password": self.password,
            "device_name": "Horus AP"
        }
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        resp = http_req(self.login_url, data=payload, headers=headers, method="POST", timeout=6, verify=False)
        if resp and isinstance(resp, dict):
            token = resp.get("token") or (resp.get("data") and isinstance(resp.get("data"), dict) and resp["data"].get("token"))
            if token:
                self.token = token
                try:
                    with open(TOKEN_FILE, "w") as f:
                        f.write(token)
                except Exception:
                    pass
                return token

        return None

    def fetch_user_info_for_mac(self, mac, token, client_ip=""):
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json"
        }

        # 1. Search by MAC address
        search_query = quote(mac)
        url = f"{self.subscribers_url}?search={search_query}"
        res = http_req(url, headers=headers, method="GET", timeout=5, verify=False)

        sub_list = []
        if res and isinstance(res, dict):
            if "data" in res and isinstance(res["data"], list):
                sub_list = res["data"]
            elif isinstance(res.get("subscribers"), list):
                sub_list = res["subscribers"]

        # 2. If not found by MAC and client IP is known from ARP table, search by IP
        if not sub_list and client_ip:
            ip_query = quote(client_ip)
            url_ip = f"{self.subscribers_url}?search={ip_query}"
            res_ip = http_req(url_ip, headers=headers, method="GET", timeout=5, verify=False)
            if res_ip and isinstance(res_ip, dict) and "data" in res_ip and isinstance(res_ip["data"], list):
                sub_list = res_ip["data"]

        if not sub_list or len(sub_list) == 0:
            return None

        sub = sub_list[0]
        sub_id = sub.get("id")
        name = sub.get("name") or sub.get("username") or ""
        uname = sub.get("username") or mac
        profile = sub.get("current_plan_name") or ""
        expiration = sub.get("expires_at_formatted") or ""
        balance = sub.get("balance", "0.00")
        loan = sub.get("total_unpaid_debt", "")
        ip = client_ip or ""
        session = 0
        quota = ""

        usage = sub.get("usage") or {}
        if isinstance(usage, dict):
            quota = usage.get("remaining") or ""

        # 3. Fetch detailed profile if ID is available (provides exact active session & remaining bytes)
        if sub_id:
            show_url = f"{self.subscribers_url}/{sub_id}"
            res_show = http_req(show_url, headers=headers, method="GET", timeout=5, verify=False)
            if res_show and isinstance(res_show, dict) and "id" in res_show:
                act_sess = res_show.get("active_session") or {}
                if isinstance(act_sess, dict):
                    session = int(act_sess.get("uptime_seconds") or 0)
                    if not ip and act_sess.get("framed_ip_address"):
                        ip = act_sess.get("framed_ip_address")
                act_sub = res_show.get("active_subscription") or {}
                if isinstance(act_sub, dict):
                    if not profile and act_sub.get("plan_name"):
                        profile = act_sub.get("plan_name")
                    if not expiration and act_sub.get("expires_at"):
                        expiration = act_sub.get("expires_at")
                    if "remaining_quota_bytes" in act_sub and act_sub["remaining_quota_bytes"] is not None:
                        quota = act_sub["remaining_quota_bytes"]
                if "balance" in res_show and res_show["balance"] is not None:
                    balance = res_show["balance"]
                if "total_unpaid_debt" in res_show and res_show["total_unpaid_debt"] is not None:
                    loan = res_show["total_unpaid_debt"]

        return {
            "mac": mac,
            "name": name,
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
                ip = mac_to_ip.get(mac, "")
                res = self.fetch_user_info_for_mac(mac, token, client_ip=ip)
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

        return results, "online"
