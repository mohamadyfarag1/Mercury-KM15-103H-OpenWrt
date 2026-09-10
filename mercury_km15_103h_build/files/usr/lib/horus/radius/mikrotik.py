# -*- coding: utf-8 -*-
"""
Horus RADIUS Sync Engine - MikroTik Direct Engine
Speaks RouterOS binary API protocol over TCP (port 8728) or TLS (port 8729),
querying /ip/hotspot/active and /ppp/active with server-side MAC filter arrays.
"""

import re

from .common import normalize_mac


def parse_routeros_uptime(val):
    """RouterOS reports session length as a duration string, not seconds --
    e.g. '1h2m3s' or, on the classic binary API, '2w3d10:20:30'. Returns 0
    for anything unrecognised rather than guessing."""
    if not val:
        return 0
    s = str(val).strip()

    m = re.match(r'^(?:(\d+)w)?(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$', s)
    if m and any(m.groups()):
        w, d, h, mi, se = (int(x) if x else 0 for x in m.groups())
        return w * 604800 + d * 86400 + h * 3600 + mi * 60 + se

    m2 = re.match(r'^(?:(\d+)w)?(?:(\d+)d)?(\d+):(\d+):(\d+)$', s)
    if m2:
        w, d, h, mi, se = (int(x) if x else 0 for x in m2.groups())
        return w * 604800 + d * 86400 + h * 3600 + mi * 60 + se

    return 0


class MikrotikApiClient:
    """Minimal RouterOS API client: the same length-prefixed word/sentence
    binary protocol RouterOS has used unchanged since v3, so this speaks to
    v6 and v7 alike. Port 8729 = api-ssl (TLS), anything else = plain TCP,
    matching RouterOS's own convention -- never both on the same port."""

    def __init__(self, host, port, timeout=6):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock = None

    def connect(self):
        # `ssl` stays out of the top-level import: python3-light has no ssl
        # module (rule 3), and importing it here would break the plain-API
        # port 8728 path too, which needs no TLS at all.
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        s.connect((self.host, self.port))
        if self.port == 8729:
            try:
                import ssl
            except ImportError:
                s.close()
                raise RuntimeError(
                    "RouterOS api-ssl (port 8729) needs the python3 ssl module, "
                    "which is not installed; use the plain API port 8728 or "
                    "install python3-openssl")
            ctx = ssl._create_unverified_context()
            s = ctx.wrap_socket(s, server_hostname=self.host)
        self.sock = s

    def close(self):
        try:
            if self.sock:
                self.sock.close()
        except Exception:
            pass
        self.sock = None

    def _write_len(self, length):
        if length < 0x80:
            self.sock.sendall(bytes([length]))
        elif length < 0x4000:
            self.sock.sendall(bytes([(length >> 8) | 0x80, length & 0xFF]))
        elif length < 0x200000:
            self.sock.sendall(bytes([(length >> 16) | 0xC0, (length >> 8) & 0xFF, length & 0xFF]))
        elif length < 0x10000000:
            self.sock.sendall(bytes([(length >> 24) | 0xE0, (length >> 16) & 0xFF, (length >> 8) & 0xFF, length & 0xFF]))
        else:
            self.sock.sendall(bytes([0xF0, (length >> 24) & 0xFF, (length >> 16) & 0xFF, (length >> 8) & 0xFF, length & 0xFF]))

    def _write_word(self, word):
        data = word.encode("utf-8")
        self._write_len(len(data))
        self.sock.sendall(data)

    def write_sentence(self, words):
        for w in words:
            self._write_word(w)
        self.sock.sendall(b"\x00")

    def _read_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("Mikrotik connection closed by peer")
            buf += chunk
        return buf

    def _read_len(self):
        b0 = self._read_exact(1)[0]
        if (b0 & 0x80) == 0x00:
            return b0
        elif (b0 & 0xC0) == 0x80:
            b1 = self._read_exact(1)[0]
            return ((b0 & 0x3F) << 8) | b1
        elif (b0 & 0xE0) == 0xC0:
            rest = self._read_exact(2)
            return ((b0 & 0x1F) << 16) | (rest[0] << 8) | rest[1]
        elif (b0 & 0xF0) == 0xE0:
            rest = self._read_exact(3)
            return ((b0 & 0x0F) << 24) | (rest[0] << 16) | (rest[1] << 8) | rest[2]
        elif b0 == 0xF0:
            rest = self._read_exact(4)
            return (rest[0] << 24) | (rest[1] << 16) | (rest[2] << 8) | rest[3]
        raise ValueError("Invalid RouterOS API length prefix byte: %r" % b0)

    def read_sentence(self):
        words = []
        while True:
            length = self._read_len()
            if length == 0:
                return words
            raw = self._read_exact(length)
            try:
                word = raw.decode("utf-8")
            except UnicodeDecodeError:
                try:
                    word = raw.decode("cp1256")
                except Exception:
                    word = raw.decode("latin1", errors="replace")
            words.append(word)

    def talk(self, words, tag):
        self.write_sentence(list(words) + [f".tag={tag}"])
        sentences = []
        while True:
            s = self.read_sentence()
            sentences.append(s)
            if "!done" in s or "!trap" in s:
                return sentences

    @staticmethod
    def _trap_message(sentences):
        for s in sentences:
            for w in s:
                if w.startswith("=message="):
                    return w[9:]
        return "RouterOS login failed"

    def login(self, username, password):
        # Attempt 1: plain credential login -- this is what RouterOS >= 6.43
        # and v7 expect, and what an older router replies to with an MD5
        # challenge embedded right in the same response (rather than a
        # separate bare `/login` probe first) so this one call covers both.
        res = self.talk(["/login", f"=name={username}", f"=password={password}"], tag="hlg1")
        if any("!trap" in s for s in res):
            raise PermissionError(self._trap_message(res))

        challenge = None
        for s in res:
            for w in s:
                if w.startswith("=ret="):
                    challenge = w[5:]
        if challenge:
            import hashlib
            chal_bytes = bytes.fromhex(challenge)
            digest = hashlib.md5(b"\x00" + password.encode("utf-8") + chal_bytes).hexdigest()
            res2 = self.talk(["/login", f"=name={username}", f"=response=00{digest}"], tag="hlg2")
            if any("!trap" in s for s in res2):
                raise PermissionError(self._trap_message(res2))

    def query(self, path, proplist=None, filters=None, tag="q"):
        """`filters` is a list of (key, value) pairs, OR'd together
        server-side via RouterOS's `?#|` operator -- the router itself does
        the matching and only sends back rows for the requested MACs,
        instead of the AP having to pull every active session and filter
        them locally."""
        words = [path]
        if proplist:
            words.append("=.proplist=" + ",".join(proplist))
        if filters:
            for k, v in filters:
                words.append(f"?{k}={v}")
            for _ in range(len(filters) - 1):
                words.append("?#|")
        sentences = self.talk(words, tag=tag)
        rows = []
        for s in sentences:
            if not s or s[0] != "!re":
                continue
            row = {}
            for w in s[1:]:
                if w.startswith("="):
                    kv = w[1:].split("=", 1)
                    if len(kv) == 2:
                        row[kv[0]] = kv[1]
            rows.append(row)
        return rows


class MikrotikEngine:
    def __init__(self, base_url, username, password, api_key=None, api_port=None):
        # Supports dedicated "api_port" config field (default 8728, or custom),
        # as well as host[:port] in base_url. Port 8729 selects api-ssl.
        host = base_url.strip()
        for prefix in ("http://", "https://"):
            if host.startswith(prefix):
                host = host[len(prefix):]
        host = host.rstrip("/")
        if api_port:
            try:
                self.port = int(str(api_port).strip())
            except ValueError:
                self.port = 8728
            self.host = host.split(":")[0]
        elif ":" in host:
            h, p = host.split(":", 1)
            self.host = h
            try:
                self.port = int(p)
            except ValueError:
                self.port = 8728
        else:
            self.host = host
            self.port = 8728
        self.username = username
        self.password = password

    def sync(self, connected_macs, mac_to_ip, ip_to_mac):
        if not connected_macs:
            return [], "online"

        macs_upper = [m.upper() for m in connected_macs if m]
        client = MikrotikApiClient(self.host, self.port, timeout=6)
        try:
            client.connect()
            client.login(self.username, self.password)

            # Hotspot active sessions carry the client's real MAC in
            # `mac-address`; PPPoE sessions carry it in `caller-id`.
            hotspot_rows = client.query(
                "/ip/hotspot/active/print",
                proplist=[
                    "user", "mac-address", "address", "uptime", "bytes-in", "bytes-out",
                    "limit-bytes-total", "limit-bytes-in", "limit-bytes-out", "session-time-left", "comment"
                ],
                filters=[("mac-address", m) for m in macs_upper],
                tag="hs",
            )
            ppp_rows = client.query(
                "/ppp/active/print",
                proplist=[
                    "name", "caller-id", "address", "uptime", "bytes-in", "bytes-out",
                    "limit-bytes-in", "limit-bytes-out", "comment"
                ],
                filters=[("caller-id", m) for m in macs_upper],
                tag="pp",
            )

            # Retrieve subscriber profiles, limits, and comments from Hotspot Users
            hs_candidates = set()
            for r in hotspot_rows:
                u = r.get("user")
                if u:
                    hs_candidates.add(u)
            for m in macs_upper:
                hs_candidates.add(m)
                norm = normalize_mac(m)
                if norm:
                    hs_candidates.add(norm)
                hs_candidates.add(m.replace(":", ""))

            hotspot_users = []
            if hs_candidates:
                hs_user_filters = [("name", c) for c in hs_candidates]
                for m in macs_upper:
                    hs_user_filters.append(("mac-address", m))
                hotspot_users = client.query(
                    "/ip/hotspot/user/print",
                    proplist=[
                        "name", "mac-address", "comment", "profile",
                        "limit-bytes-total", "limit-bytes-in", "limit-bytes-out",
                        "bytes-in", "bytes-out", "limit-uptime", "uptime"
                    ],
                    filters=hs_user_filters,
                    tag="hsu",
                )

            # Retrieve subscriber profiles, limits, and comments from PPP Secrets
            ppp_candidates = set()
            for r in ppp_rows:
                u = r.get("name")
                if u:
                    ppp_candidates.add(u)
            for m in macs_upper:
                ppp_candidates.add(m)
                norm = normalize_mac(m)
                if norm:
                    ppp_candidates.add(norm)

            ppp_secrets = []
            if ppp_candidates:
                ppp_user_filters = [("name", c) for c in ppp_candidates]
                ppp_secrets = client.query(
                    "/ppp/secret/print",
                    proplist=[
                        "name", "caller-id", "comment", "profile",
                        "limit-bytes-total", "limit-bytes-in", "limit-bytes-out",
                        "bytes-in", "bytes-out"
                    ],
                    filters=ppp_user_filters,
                    tag="pps",
                )
        except Exception:
            return [], "offline"
        finally:
            client.close()

        hotspot_user_map = {}
        for urow in hotspot_users:
            uname = urow.get("name")
            umac = normalize_mac(urow.get("mac-address") or "")
            if uname:
                hotspot_user_map[uname] = urow
                norm_uname = normalize_mac(uname)
                if norm_uname:
                    hotspot_user_map[norm_uname] = urow
            if umac:
                hotspot_user_map[umac] = urow

        ppp_secret_map = {}
        for srow in ppp_secrets:
            sname = srow.get("name")
            scaller = normalize_mac(srow.get("caller-id") or "")
            if sname:
                ppp_secret_map[sname] = srow
                norm_sname = normalize_mac(sname)
                if norm_sname:
                    ppp_secret_map[norm_sname] = srow
            if scaller:
                ppp_secret_map[scaller] = srow

        def to_int(v, default=0):
            try:
                return int(v)
            except (ValueError, TypeError):
                return default

        import time

        by_mac = {}
        for row in hotspot_rows:
            m = normalize_mac(row.get("mac-address") or "")
            if not m:
                continue

            u = row.get("user") or m
            user_rec = hotspot_user_map.get(u) or hotspot_user_map.get(m) or {}

            # 1. Subscriber Name from comment (clean whitespace/newlines)
            raw_comment = (user_rec.get("comment") or row.get("comment") or "").strip()
            comment = " ".join(raw_comment.split()) if raw_comment else ""
            display_name = comment if comment else u

            # 2. Limits and usage
            limit_total = to_int(user_rec.get("limit-bytes-total") or row.get("limit-bytes-total"))
            limit_in = to_int(user_rec.get("limit-bytes-in") or row.get("limit-bytes-in"))
            limit_out = to_int(user_rec.get("limit-bytes-out") or row.get("limit-bytes-out"))

            act_in = to_int(row.get("bytes-in"))
            act_out = to_int(row.get("bytes-out"))
            usr_in = to_int(user_rec.get("bytes-in"))
            usr_out = to_int(user_rec.get("bytes-out"))

            total_used = max(usr_in + usr_out, act_in + act_out)
            if total_used == 0 and (usr_in + usr_out + act_in + act_out) > 0:
                total_used = usr_in + usr_out + act_in + act_out

            quota_remaining = ""
            if limit_total > 1:
                quota_remaining = max(0, limit_total - total_used)
            elif limit_in > 1:
                rem_in = max(0, limit_in - max(usr_in, act_in))
                rem_out = max(0, limit_out - max(usr_out, act_out)) if limit_out > 1 else 0
                quota_remaining = rem_in + rem_out
            elif limit_total == 1:
                quota_remaining = 0

            # Expiration
            expiration = ""
            sess_left_str = row.get("session-time-left")
            if sess_left_str:
                secs_left = parse_routeros_uptime(sess_left_str)
                if secs_left > 0:
                    expiration = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() + secs_left))
            if not expiration and user_rec.get("limit-uptime"):
                limit_up = parse_routeros_uptime(user_rec.get("limit-uptime"))
                used_up = parse_routeros_uptime(user_rec.get("uptime"))
                rem_up = max(0, limit_up - used_up)
                if rem_up > 0:
                    expiration = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() + rem_up))

            profile = user_rec.get("profile") or row.get("profile") or ""

            by_mac[m] = {
                "name": display_name,
                "username": u,
                "ip": row.get("address") or "",
                "session": parse_routeros_uptime(row.get("uptime")),
                "quota": quota_remaining,
                "used": total_used,
                "profile": profile,
                "expiration": expiration
            }

        for row in ppp_rows:
            m = normalize_mac(row.get("caller-id") or "")
            if not m or m in by_mac:
                continue

            u = row.get("name") or m
            user_rec = ppp_secret_map.get(u) or ppp_secret_map.get(m) or {}

            raw_comment = (user_rec.get("comment") or row.get("comment") or "").strip()
            comment = " ".join(raw_comment.split()) if raw_comment else ""
            display_name = comment if comment else u

            limit_total = to_int(user_rec.get("limit-bytes-total") or row.get("limit-bytes-total"))
            limit_in = to_int(user_rec.get("limit-bytes-in") or row.get("limit-bytes-in"))
            limit_out = to_int(user_rec.get("limit-bytes-out") or row.get("limit-bytes-out"))

            act_in = to_int(row.get("bytes-in"))
            act_out = to_int(row.get("bytes-out"))
            usr_in = to_int(user_rec.get("bytes-in"))
            usr_out = to_int(user_rec.get("bytes-out"))

            total_used = max(usr_in + usr_out, act_in + act_out)
            if total_used == 0 and (usr_in + usr_out + act_in + act_out) > 0:
                total_used = usr_in + usr_out + act_in + act_out

            quota_remaining = ""
            if limit_total > 1:
                quota_remaining = max(0, limit_total - total_used)
            elif limit_in > 1:
                rem_in = max(0, limit_in - max(usr_in, act_in))
                rem_out = max(0, limit_out - max(usr_out, act_out)) if limit_out > 1 else 0
                quota_remaining = rem_in + rem_out
            elif limit_total == 1:
                quota_remaining = 0

            profile = user_rec.get("profile") or row.get("profile") or ""

            by_mac[m] = {
                "name": display_name,
                "username": u,
                "ip": row.get("address") or "",
                "session": parse_routeros_uptime(row.get("uptime")),
                "quota": quota_remaining,
                "used": total_used,
                "profile": profile,
                "expiration": ""
            }

        for m in macs_upper:
            norm_m = normalize_mac(m)
            if norm_m not in by_mac:
                user_rec = hotspot_user_map.get(m) or hotspot_user_map.get(norm_m) or ppp_secret_map.get(m) or ppp_secret_map.get(norm_m)
                if user_rec:
                    raw_comment = (user_rec.get("comment") or "").strip()
                    comment = " ".join(raw_comment.split()) if raw_comment else ""
                    display_name = comment if comment else norm_m
                    limit_total = to_int(user_rec.get("limit-bytes-total"))
                    usr_in = to_int(user_rec.get("bytes-in"))
                    usr_out = to_int(user_rec.get("bytes-out"))
                    total_used = usr_in + usr_out
                    quota_remaining = ""
                    if limit_total > 1:
                        quota_remaining = max(0, limit_total - total_used)
                    elif limit_total == 1:
                        quota_remaining = 0

                    by_mac[norm_m] = {
                        "name": display_name,
                        "username": user_rec.get("name") or norm_m,
                        "ip": "",
                        "session": 0,
                        "quota": quota_remaining,
                        "used": total_used,
                        "profile": user_rec.get("profile") or "",
                        "expiration": ""
                    }

        results = []
        for mac in connected_macs:
            info = by_mac.get(mac)
            if not info:
                continue
            ip = mac_to_ip.get(mac, "")
            results.append({
                "mac": mac,
                "name": info["name"],
                "profile": info["profile"],
                "expiration": info["expiration"],
                "quota": info["quota"],
                "used": info["used"],
                "balance": "",
                "loan": "",
                "ip": info["ip"] or ip,
                "session": info["session"],
                "username": info["username"]
            })
        return results, "online"
