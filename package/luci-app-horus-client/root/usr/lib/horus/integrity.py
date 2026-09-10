# -*- coding: utf-8 -*-
"""Runtime tamper detection for the Horus daemon/logic files.

HONEST SCOPE
    This is NOT a barrier against a determined root user. On hardware the
    attacker controls, any on-device check can ultimately be patched out and
    the embedded manifest key can be extracted. What this DOES buy, in a
    managed mesh, is *detection*: it notices when a shipped daemon/logic file
    was modified and surfaces that to the controller (telemetry `integrity`
    field), so an operator can spot and quarantine a node whose code was
    altered. The manifest is HMAC-signed, so a third party must also forge the
    signature (its key lives only inside the obfuscated build) — that raises
    the bar for casual tampering without pretending to be unbreakable.

WHAT IS CHECKED
    A build-time manifest (`.horus_manifest.json`, next to this module) maps
    each shipped daemon file (`/usr/lib/horus/**.py`, `/usr/bin/horus-*.py`,
    `/www/cgi-bin/horus*`) to its SHA-256, plus an HMAC signature over the map.
    Absent manifest (e.g. an older build) => reported as "not enforced", never
    as tampered, so upgrades never false-positive.
"""
import os
import json
import time
import hmac
import hashlib
import threading

_DIR = os.path.dirname(os.path.abspath(__file__))
_MANIFEST = os.path.join(_DIR, ".horus_manifest.json")

# Embedded at build; obfuscated by the secure packer. Extractable by root
# (documented limitation) — its purpose is to stop *casual* manifest forgery.
_MANIFEST_KEY = b"HorusIntegrity_Manifest_HMAC_2026"

_lock = threading.Lock()
_started = {"v": False}
_status = {"ok": True, "checked": 0, "mismatched": [], "manifest": False, "ts": 0}


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _canonical(files):
    return json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")


def verify_now():
    """Recompute and cache the integrity status. Returns a copy of it."""
    result = {"ok": True, "checked": 0, "mismatched": [], "manifest": False,
              "ts": int(time.time())}
    try:
        with open(_MANIFEST, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        files = manifest.get("files", {})
        sig = manifest.get("sig", "")
    except Exception:
        # No/unreadable manifest: unknown, treated as OK-but-not-enforced.
        with _lock:
            _status.update(result)
        return dict(result)

    result["manifest"] = True

    # 1. Manifest signature — catches a naive edit of the file list itself.
    expected_sig = hmac.new(_MANIFEST_KEY, _canonical(files), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(str(sig), expected_sig):
        result["ok"] = False
        result["mismatched"].append("<manifest-signature>")

    # 2. Per-file content.
    for path, want in files.items():
        result["checked"] += 1
        try:
            got = _sha256_file(path)
        except Exception:
            got = None
        if got != want:
            result["ok"] = False
            result["mismatched"].append(path)

    with _lock:
        _status.update(result)
    return dict(result)


def get_status():
    with _lock:
        return dict(_status)


def telemetry_status():
    """Compact status for the telemetry payload (bounded size)."""
    s = get_status()
    bad = list(s.get("mismatched", []))
    return {
        "ok": bool(s.get("ok", True)),
        "enforced": bool(s.get("manifest", False)),
        "n_bad": len(bad),
        "bad": bad[:10],
        "ts": s.get("ts", 0),
    }


def start_periodic(interval=300):
    """Run one check now, then re-check every `interval` seconds (idempotent)."""
    with _lock:
        if _started["v"]:
            return
        _started["v"] = True

    def _loop():
        while True:
            try:
                verify_now()
            except Exception:
                pass
            time.sleep(interval)

    try:
        verify_now()
    except Exception:
        pass
    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    return t
