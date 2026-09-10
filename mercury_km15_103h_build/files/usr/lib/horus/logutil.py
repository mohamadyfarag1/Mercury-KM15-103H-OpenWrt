# -*- coding: utf-8 -*-
"""Lightweight, dependency-free logging for the Horus daemons.

WHY
    The daemons historically used a `DummyLog` no-op, so 155 `except` blocks
    swallowed every error with zero trace on the device -- impossible to debug
    a real AP. This routes those same `log.*` calls to the system log instead.

HOW
    Messages are written to **stderr**, which procd already forwards into the
    system ring buffer (`logread`) because `init.d/horus_client` sets
    `procd_set_param stderr 1`. That means:
      * no `/dev/log`, no `logging.handlers`, nothing outside `python3-light`
        (see AI_AGENT_RULES rule 25 -- only core stdlib is safe on the APs);
      * logs live in RAM (syslog ring buffer), so there is **no flash wear**.

    The verbosity is read once from UCI `horus_controller.main.log_level`
    (debug|info|warning|error|none, default: warning). If anything goes wrong
    while configuring logging, we fall back to a silent no-op logger -- a
    logging problem must never take a daemon down.
"""
import sys

_LEVELS = ("debug", "info", "warning", "error", "none")
_state = {"configured": False}


class _NullLog:
    """Silent fallback with the same surface as logging.Logger."""
    def debug(self, *a, **k): pass
    def info(self, *a, **k): pass
    def warning(self, *a, **k): pass
    def error(self, *a, **k): pass
    def exception(self, *a, **k): pass


def _read_level():
    try:
        import subprocess
        out = subprocess.check_output(
            "uci -q get horus_controller.main.log_level",
            shell=True, text=True).strip().lower()
        if out in _LEVELS:
            return out
    except Exception:
        pass
    return "warning"


def get_logger(name="horus"):
    """Return a real stderr-backed logger, or a no-op logger on any failure."""
    try:
        import logging
        level_name = _read_level()
        if level_name == "none":
            return _NullLog()

        parent = logging.getLogger("horus")
        if not _state["configured"]:
            parent.setLevel(getattr(logging, level_name.upper(), logging.WARNING))
            if not parent.handlers:
                handler = logging.StreamHandler(sys.stderr)
                handler.setFormatter(
                    logging.Formatter("horus[%(name)s] %(levelname)s: %(message)s"))
                parent.addHandler(handler)
            parent.propagate = False  # don't double-log via the root logger
            _state["configured"] = True

        return logging.getLogger(name if name.startswith("horus") else "horus." + name)
    except Exception:
        return _NullLog()
