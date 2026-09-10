# -*- coding: utf-8 -*-
import os
import sys
import time
import select
import threading
import subprocess
from .config import HELLO_INTERVAL, TELEMETRY_INTERVAL
from .system import get_uci, get_my_mac, get_hostname
from .protocol import send_hmp_frame, parse_incoming_data

from .sat_actions import (
    execute_ban_unban, execute_wifi_config, execute_ap_manage, send_cmd_ack
)
from .sat_peers import (
    send_peer_announce, handle_peer_announce, clear_peers_file, calculate_peer_ttl, PEERS_FILE
)
from .sat_telemetry import (
    send_hello_once, send_telemetry_once, handle_root_heartbeat, is_controller_managed, CONTROLLER_INFO_FILE
)

from .logutil import get_logger
log = get_logger("horus.satellite")


class SatelliteNode:
    def __init__(self, raw_sock, udp_sock, secret, controller_ip=""):
        self.raw_sock = raw_sock
        self.udp_sock = udp_sock
        self.secret = secret
        self.controller_ip = controller_ip if controller_ip else ""
        self.my_mac = get_my_mac()
        self.my_hostname = get_hostname()
        self.controller_mac = (get_uci("horus_controller.main.controller_mac", "") or "").upper()
        self.neighbors_enabled = get_uci("horus_controller.main.neighbors_enabled", "1") == "1"
        try:
            self.neighbors_interval = int(get_uci("horus_controller.main.neighbors_interval", "30"))
        except Exception:
            self.neighbors_interval = 30
        self.last_l2_seen = 0

    def send_to_root(self, payload):
        """Send a payload frame to root controller."""
        send_hmp_frame(
            self.raw_sock, self.udp_sock, payload,
            dst_mac="FF:FF:FF:FF:FF:FF", dst_ip=self.controller_ip, secret=self.secret
        )

    def peer_ttl(self):
        return calculate_peer_ttl(self.neighbors_interval)

    def is_controller_managed(self):
        return is_controller_managed(self)

    def clear_peers_file(self):
        clear_peers_file()

    def sync_identity_from_uci(self):
        """Pick up out-of-band changes to hmp_secret / controller_mac."""
        try:
            uci_secret = get_uci("horus_controller.main.hmp_secret", "")
            if uci_secret != self.secret:
                self.secret = uci_secret
                if not uci_secret:
                    self.controller_mac = ""
                    try:
                        os.remove(CONTROLLER_INFO_FILE)
                    except OSError:
                        pass
                    log.info("hmp_secret cleared locally; resuming controller discovery")
            if self.secret:
                self.controller_mac = (get_uci("horus_controller.main.controller_mac", "") or "").upper()
            else:
                self.controller_mac = ""

            self.controller_ip = get_uci("horus_controller.main.controller_ip", "") or ""
        except Exception:
            log.exception("identity sync from UCI failed")

    def unadopt(self, reason=""):
        """Forget our controller and become adoptable again."""
        try:
            subprocess.run("uci set horus_controller.main.hmp_secret=''", shell=True)
            subprocess.run("uci set horus_controller.main.controller_mac=''", shell=True)
            subprocess.run("uci commit horus_controller", shell=True)
            self.secret = ""
            self.controller_mac = ""
            try:
                os.remove(CONTROLLER_INFO_FILE)
            except OSError:
                pass
            log.info("unadopted (%s); now discoverable by any controller", reason or "by controller")
        except Exception:
            log.exception("unadopt failed")

    def send_hello_once(self):
        send_hello_once(self)

    def send_telemetry_once(self):
        send_telemetry_once(self)

    def hello_loop(self):
        while True:
            try:
                self.sync_identity_from_uci()
                self.send_hello_once()
            except Exception:
                pass
            time.sleep(HELLO_INTERVAL)

    def telemetry_loop(self):
        # Start tamper-detection once the daemon is up (idempotent, best-effort).
        try:
            from .integrity import start_periodic
            start_periodic()
        except Exception:
            pass
        while True:
            try:
                self.send_telemetry_once()
            except Exception:
                pass
            time.sleep(TELEMETRY_INTERVAL)

    def send_peer_announce(self):
        send_peer_announce(self)

    def peer_loop(self):
        while True:
            try:
                self.send_peer_announce()
            except Exception:
                pass
            time.sleep(self.neighbors_interval)

    def listen_loop(self):
        sockets = [s for s in [self.raw_sock, self.udp_sock] if s]

        while True:
            try:
                readable, _, _ = select.select(sockets, [], [], 1.0)
                for s in readable:
                    data = None
                    is_l2 = False
                    if s == self.raw_sock:
                        try:
                            data, sll = s.recvfrom(4096)
                            if len(sll) >= 3 and sll[2] == 4:
                                continue
                        except Exception:
                            data = s.recv(4096)
                        is_l2 = True
                    else:
                        data, addr = s.recvfrom(4096)
                        is_l2 = False

                    if not data:
                        continue

                    data = parse_incoming_data(data, is_l2=is_l2, secret=self.secret, my_mac=self.my_mac)
                    if not data:
                        continue

                    is_auth = data.get('_is_auth', False)
                    msg_type = data.get("type", "")
                    # Tolerate a malformed frame carrying target_mac: null.
                    target_ap = (data.get("target_mac") or "").upper()
                    cmd_id = data.get("cmd_id", "")
                    ack_secret = self.secret

                    # Destination check
                    if msg_type in ["wifi_config", "ap_manage", "root_heartbeat", "root_announce"]:
                        if target_ap and target_ap != "FF:FF:FF:FF:FF:FF" and target_ap != "ALL" and target_ap != self.my_mac:
                            continue

                    # HMAC security checks
                    if self.secret and not is_auth:
                        if msg_type != "peer_announce":
                            continue

                    if not self.secret:
                        if msg_type not in ["root_heartbeat", "root_announce", "peer_announce"]:
                            if msg_type != "ap_manage" or data.get("action") != "set_api_key":
                                continue

                    # Dispatch to modular handlers
                    if msg_type == "peer_announce":
                        handle_peer_announce(self, data, is_l2)
                    elif msg_type in ["root_heartbeat", "root_announce"]:
                        handle_root_heartbeat(self, data, is_l2, target_ap)
                    elif msg_type in ["ban", "unban"]:
                        execute_ban_unban(self, data, msg_type)
                    elif msg_type == "wifi_config":
                        execute_wifi_config(self, data)
                    elif msg_type == "ap_manage":
                        execute_ap_manage(self, data, ack_secret)

                    # Acknowledge command receipt if cmd_id is present
                    send_cmd_ack(self, data, ack_secret)

            except Exception:
                log.exception("listen_loop packet handling failed")
