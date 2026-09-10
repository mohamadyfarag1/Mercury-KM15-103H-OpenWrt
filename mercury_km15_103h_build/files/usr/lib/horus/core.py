# -*- coding: utf-8 -*-
import sys
import threading
from .system import get_uci
from .protocol import create_sockets
from .satellite import SatelliteNode

def main():
    role = get_uci("horus_controller.main.role", "standalone")
    neighbors_enabled = get_uci("horus_controller.main.neighbors_enabled", "1") == "1"
    
    if role == "standalone" and not neighbors_enabled:
        sys.exit(0)
    
    secret = get_uci("horus_controller.main.hmp_secret", "")
    controller_ip = get_uci("horus_controller.main.controller_ip", "")
    
    raw_sock, udp_sock = create_sockets()
    if not raw_sock and not udp_sock:
        print("Fatal: Could not initialize network sockets.")
        sys.exit(1)

    if role == "satellite":
        node = SatelliteNode(raw_sock, udp_sock, secret, controller_ip=controller_ip)
        threading.Thread(target=node.listen_loop, daemon=True).start()
        threading.Thread(target=node.hello_loop, daemon=True).start()
        # Always start peer_loop: it re-reads neighbors_enabled (and the
        # controller-managed check) every tick and returns early when it should
        # stay quiet. Gating the thread's creation on the boot-time value meant
        # enabling P2P in the UI did nothing until the daemon was restarted.
        threading.Thread(target=node.peer_loop, daemon=True).start()
        node.telemetry_loop()
    elif role == "standalone" and neighbors_enabled:
        node = SatelliteNode(raw_sock, udp_sock, secret="", controller_ip="")
        threading.Thread(target=node.listen_loop, daemon=True).start()
        node.peer_loop()
    elif role == "root":
        try:
            from .root import RootNode
            grace_period_str = get_uci("horus_controller.main.grace_period", "30")
            try: grace_period = int(grace_period_str)
            except: grace_period = 30
            node = RootNode(raw_sock, udp_sock, secret, grace_period)
            try:
                from .rrm import background_scan_loop
                threading.Thread(target=background_scan_loop, daemon=True).start()
            except ImportError:
                pass
            threading.Thread(target=node.listen_loop, daemon=True).start()
            threading.Thread(target=node.fast_cmd_loop, daemon=True).start()
            node.maintenance_loop()
        except ImportError:
            print("Root mode not supported on client package")
            sys.exit(1)
    else:
        sys.exit(0)
