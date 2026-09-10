# -*- coding: utf-8 -*-
"""
Horus RADIUS Sync Engine - Embedded HTTP/HTTPS Client
Supports raw socket HTTP 1.0, TLS with SNI fallback, and system tools
(curl/uclient-fetch) fallback for python3-light environments lacking native ssl.
"""

import sys
import json
import subprocess


def quote(s):
    res = []
    for c in str(s):
        if c.isalnum() or c in '-_.~':
            res.append(c)
        else:
            res.append('%{:02X}'.format(ord(c)))
    return "".join(res)


def custom_urlencode(params):
    return "&".join([f"{quote(k)}={quote(v)}" for k, v in params.items()])


def _have(tool):
    try:
        return subprocess.call("command -v %s >/dev/null 2>&1" % tool, shell=True) == 0
    except Exception:
        return False


def _http_req_via_tool(url, payload, headers, method, timeout, verify):
    """HTTPS fallback for devices whose python3-light has no `ssl` module.

    Shells out to curl (preferred -- it is the only one of the two that can
    send arbitrary headers, which the SAS/UM7 engines need for
    Authorization) or uclient-fetch, both of which link libustream and do
    real TLS. Returns the parsed JSON body, or None, matching http_req().
    """
    try:
        if _have("curl"):
            cmd = ["curl", "-s", "-m", str(timeout)]
            if not verify:
                cmd.append("-k")
            if method and method != "GET":
                cmd += ["-X", method]
            for k, v in headers.items():
                cmd += ["-H", "%s: %s" % (k, v)]
            if payload:
                cmd += ["--data-binary", payload]
            cmd.append(url)
        elif _have("uclient-fetch"):
            # No header support (verified on-device); fine for the
            # query-string-authenticated engines (DMA/ICM), not for bearer ones.
            cmd = ["uclient-fetch", "-q", "-O", "-", "-T", str(timeout)]
            if not verify:
                cmd.append("--no-check-certificate")
            if payload:
                cmd.append("--post-data=" + payload)
            cmd.append(url)
        else:
            log_once_no_tls()
            return None

        out = subprocess.run(cmd, capture_output=True, timeout=timeout + 4).stdout
        if not out:
            return None
        return json.loads(out.decode("utf-8", errors="ignore"))
    except Exception:
        return None


_warned_no_tls = [False]


def log_once_no_tls():
    if not _warned_no_tls[0]:
        _warned_no_tls[0] = True
        sys.stderr.write(
            "horus-radius: https:// configured but this device has neither the "
            "python3 ssl module nor curl/uclient-fetch -- install python3-openssl "
            "or curl, or use http://\n")


def http_req(url, data=None, headers=None, method=None, timeout=6, verify=True):
    if headers is None:
        headers = {}

    # `ssl` is NOT imported here on purpose -- it is not part of
    # python3-light, which is all these APs ship (see AI_AGENT_RULES.md
    # rule 3). Importing it at the top of this function raised ImportError on
    # EVERY call, including plain-http ones, which silently reported every
    # RADIUS server on every AP as "offline". It is imported lazily inside
    # the `use_tls` branch below, where its absence can be reported honestly
    # instead of taking the whole sync down with it.
    import socket

    use_tls = url.startswith("https://")
    if url.startswith("http://"):
        url = url[7:]
    elif url.startswith("https://"):
        url = url[8:]

    parts = url.split('/', 1)
    host_port = parts[0]
    path = '/' + parts[1] if len(parts) > 1 else '/'

    if ':' in host_port:
        host, port = host_port.split(':', 1)
        port = int(port)
    else:
        host = host_port
        port = 443 if use_tls else 80

    if data is not None:
        if isinstance(data, dict):
            if headers.get('Content-Type') == 'application/x-www-form-urlencoded':
                payload = custom_urlencode(data)
            else:
                payload = json.dumps(data)
                headers['Content-Type'] = 'application/json'
        else:
            payload = str(data)
            if 'Content-Type' not in headers:
                headers['Content-Type'] = 'application/json'
        method = method or 'POST'
    else:
        payload = ""
        method = method or 'GET'

    payload_bytes = payload.encode('utf-8') if payload else b""

    req = f"{method} {path} HTTP/1.0\r\n"
    req += f"Host: {host}\r\n"
    req += "Connection: close\r\n"
    for k, v in headers.items():
        req += f"{k}: {v}\r\n"
    
    if payload_bytes:
        req += f"Content-Length: {len(payload_bytes)}\r\n\r\n"
    else:
        req += "\r\n"

    req_bytes = req.encode('utf-8') + payload_bytes

    if use_tls:
        try:
            import ssl
        except ImportError:
            # python3-light has no ssl module. Rather than fail, hand the
            # request to a system HTTP client that links libustream and can
            # actually do TLS. Plain-http requests never reach this branch.
            return _http_req_via_tool(
                ("https://%s:%d%s" % (host, port, path)), payload, headers, method, timeout, verify)

    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((host, port))
        if use_tls:
            if verify:
                ctx = ssl.create_default_context()
            else:
                # For devices that manage their own HTTPS with a self-signed
                # cert (e.g. a MikroTik router's REST API out of the box) --
                # not for the RADIUS panels, which are expected to have a
                # real cert if they're https:// at all.
                ctx = ssl._create_unverified_context()
            s = ctx.wrap_socket(s, server_hostname=host)
        s.sendall(req_bytes)

        resp = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            resp += chunk
        
        resp_str = resp.decode('utf-8', errors='ignore')
        if "\r\n\r\n" in resp_str:
            body = resp_str.split("\r\n\r\n", 1)[1]
        else:
            body = resp_str

        if body:
            return json.loads(body)
    except Exception:
        pass
    finally:
        if s:
            try:
                s.close()
            except Exception:
                pass
    return None

