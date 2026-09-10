# -*- coding: utf-8 -*-
import os
import time
import json
import select
import threading
import subprocess
from .config import (
    AP_DEAD_TIMEOUT, BAN_CMD_FILE, WIFI_CMD_FILE, AP_CMD_FILE, STATE_FILE
)
from .system import (
    get_my_mac, get_lan_ip, get_lan_netmask, get_lan_gateway, get_hostname, get_wireless_macs,
    get_wifi_info, get_ethernet_ports, get_system_stats, get_wifi_radios_and_macs,
    ban_mac_locally, unban_mac_locally, apply_wifi_config, steer_client_locally
)
from .rrm import get_scan_data
from .protocol import send_hmp_frame, parse_incoming_data
from .db import HorusDB
from .system import get_uci

from .logutil import get_logger
log = get_logger("horus.root")


class RootNode:
    def __init__(self, raw_sock, udp_sock, secret, grace_period):
        self.raw_sock = raw_sock
        self.udp_sock = udp_sock
        self.secret = secret
        self.grace_period = grace_period
        self.my_mac = get_my_mac()

        self.db = HorusDB()
        self.db.set_my_mac(self.my_mac)

        self.rrm_counter = 0
        self.lock = threading.Lock()

    def send_cmd(self, payload, dst_mac='FF:FF:FF:FF:FF:FF', secret=None):
        dst_ip = ""
        if dst_mac and dst_mac != 'FF:FF:FF:FF:FF:FF':
            real_addr = self.db.get_ap_real_addr(dst_mac)
            if real_addr and real_addr != '0.0.0.0':
                dst_ip = real_addr
        send_hmp_frame(self.raw_sock, self.udp_sock, payload, dst_mac=dst_mac, dst_ip=dst_ip,
                        secret=self.secret if secret is None else secret)

    def listen_loop(self):
        sockets = [s for s in [self.raw_sock, self.udp_sock] if s]

        while True:
            try:
                readable, _, _ = select.select(sockets, [], [], 1.0)
                for s in readable:
                    if s == self.raw_sock:
                        try:
                            raw_frame, sll = s.recvfrom(4096)
                            if len(sll) >= 3 and sll[2] == 4:
                                continue
                        except Exception:
                            raw_frame = s.recv(4096)
                        data = parse_incoming_data(raw_frame, is_l2=True, secret=self.secret)
                        real_addr = None
                    else:
                        udp_data, real_addr = s.recvfrom(4096)
                        data = parse_incoming_data(udp_data, is_l2=False, secret=self.secret)
                        if data and 'ip' not in data:
                            data['ip'] = real_addr[0]

                    if not data:
                        continue

                    src_mac = data.get('src_mac', '').upper()
                    if not src_mac or src_mac == self.my_mac:
                        continue
                    
                    is_auth = data.get('_is_auth', False)
                    msg_type = data.get('type', '')
                    now = time.time()
                    
                    if not is_auth and msg_type not in ['hello', 'telemetry', 'peer_announce']:
                        continue

                    # Adoption lock: an AP already owned by another controller
                    # advertises adopted_by=<that controller's MAC>. Never
                    # treat it as ours -- don't ACK it, don't put it in
                    # self.db.state["aps"] (that dict is what RRM, smart
                    # steering, and anti-spoof iterate expecting every entry
                    # to be a device we're allowed to command; without this
                    # check its frames would fail our HMAC and land there as
                    # "unauthorized", i.e. offered up for stealing). It still
                    # gets a minimal, deliberately separate record so the UI
                    # can show it as owned elsewhere instead of the AP just
                    # silently never appearing.
                    if msg_type in ['hello', 'telemetry']:
                        adopted_by = str(data.get('adopted_by', '') or '').upper()
                        if adopted_by and adopted_by != self.my_mac:
                            self.db.note_foreign_ap(src_mac, data.get('hostname', ''), data.get('ip', ''), adopted_by, now)
                            continue

                    if msg_type in ['hello', 'telemetry']:
                        # Reply with heartbeat ACK so the Satellite AP knows it is 100% connected
                        ap_db = self.db.state.get("aps", {}).get(src_mac, {})
                        is_auth_status = not ap_db.get("unauthorized", False)
                        
                        ack_payload = {
                            'type': 'root_heartbeat',
                            'src_mac': self.my_mac,
                            # This ACK answers exactly one AP's hello/telemetry.
                            # send_hmp_frame() broadcasts at the Ethernet layer
                            # (so bridges/WDS don't drop unlearned MACs), so the
                            # intended recipient must be named in the payload or
                            # every AP on the segment would read someone else's
                            # ACK as proof of its own connectivity.
                            'target_mac': src_mac,
                            'root_ip': get_lan_ip(),
                            'root_hostname': get_hostname(),
                            'is_authorized': is_auth_status,
                            'ts': now
                        }
                        # Send ACK via pure Layer 2 directly to the AP MAC
                        self.send_cmd(ack_payload, dst_mac=src_mac)

                    if msg_type == 'hello':
                        with self.lock:
                            self.db.update_ap(
                                mac=src_mac,
                                hostname=data.get('hostname', 'unknown'),
                                ip=data.get('ip', ''),
                                last_seen=now,
                                wifi_info=data.get('wifi', []),
                                scan_data={},
                                ports=data.get('ports', []),
                                stats=data.get('stats', {}),
                                real_addr=real_addr,
                                netmask=data.get('netmask', '255.255.255.0'),
                                gateway=data.get('gateway', ''),
                                unauthorized=not is_auth,
                                radio_macs=data.get('radio_macs', [])
                            )
                    elif msg_type == 'telemetry':
                        clients = data.get('clients', [])
                        scan_data = data.get('scan_data', {})
                        with self.lock:
                            self.db.update_ap(
                                mac=src_mac,
                                hostname=data.get('hostname', 'Horus-AP'),
                                ip=data.get('ip', ''),
                                last_seen=now,
                                wifi_info=data.get('wifi', []),
                                scan_data=scan_data,
                                ports=data.get('ports', []),
                                stats=data.get('stats', {}),
                                real_addr=real_addr,
                                netmask=data.get('netmask', '255.255.255.0'),
                                gateway=data.get('gateway', ''),
                                unauthorized=not is_auth,
                                radio_macs=data.get('radio_macs', [])
                            )
                            if is_auth:
                                self.db.update_clients(src_mac, clients, now)
                                self.handle_anti_spoofing(now)
                    elif msg_type == 'cmd_ack':
                        cmd_id = data.get('cmd_id', '')
                        if cmd_id:
                            with self.lock:
                                self.db.mark_cmd_result(cmd_id, ok=data.get('ok', True), error=data.get('error', ''))
                    elif msg_type == 'pkg_install_result':
                        src_mac_up = str(src_mac).upper()
                        success = data.get('success', False)
                        msg = data.get('message', '')
                        pkg_name = data.get('package', '')
                        try:
                            st_file = "/tmp/horus_pkg_status.json"
                            st_data = {}
                            if os.path.exists(st_file):
                                with open(st_file, "r") as sf:
                                    st_data = json.load(sf)
                            if "targets" not in st_data:
                                st_data["targets"] = {}
                            st_data["targets"][src_mac_up] = {
                                "status": "success" if success else "error",
                                "message": msg,
                                "package": pkg_name,
                                "ts": int(now)
                            }
                            with open(st_file, "w") as sf:
                                json.dump(st_data, sf)
                        except Exception:
                            pass
                    elif msg_type == 'peer_announce':
                        peer_src = src_mac.upper()
                        if peer_src != self.my_mac:
                            peer_host = data.get("hostname", "Horus-AP")
                            peer_ip = data.get("ip", "")
                            peer_5g = [m.upper() for m in data.get("radios_5g", [])]
                            peer_2g = [m.upper() for m in data.get("radios_2g", [])]
                            peer_macs = [m.upper() for m in data.get("macs", [])]
                            if peer_src not in peer_macs:
                                peer_macs.append(peer_src)
                            mac_5g = (data.get("mac_5g") or "").upper()
                            if mac_5g and mac_5g not in peer_macs:
                                peer_macs.append(mac_5g)
                            mac_lan = (data.get("mac_lan") or "").upper()
                            if mac_lan and mac_lan not in peer_macs:
                                peer_macs.append(mac_lan)
                            try:
                                peers_db = {}
                                if os.path.exists("/tmp/horus_ap_peers.json"):
                                    try:
                                        with open("/tmp/horus_ap_peers.json", "r") as f:
                                            peers_db = json.load(f)
                                    except Exception:
                                        pass
                                now_t = int(now)
                                try:
                                    _iv = int(get_uci("horus_controller.main.neighbors_interval", "30"))
                                except Exception:
                                    _iv = 30
                                _ttl = max(90, _iv * 3)
                                peers_db = {k: v for k, v in peers_db.items() if (now_t - v.get("last_seen", 0)) < _ttl}
                                
                                from .sys_wifi import get_5g_channel_health
                                from .sat_peers import sync_peer_host_hints
                                local_wifi = {c['mac'].upper(): c for c in get_wireless_macs()}
                                local_health = get_5g_channel_health()
                                local_connected_bssid = local_health.get("connected_bssid", "").upper()
                                p_health = data.get("health_5g", {})
                                
                                channel_match_5g = bool(
                                    local_health.get("has_5g") and
                                    p_health.get("channel") and
                                    local_health.get("channel") and
                                    p_health.get("channel") == local_health.get("channel") and
                                    (
                                        (p_health.get("mode") == "ap" and local_health.get("mode") == "sta") or
                                        (p_health.get("mode") == "sta" and local_health.get("mode") == "ap")
                                    )
                                )
                                
                                peer_is_wireless = (
                                    bool(any(pm in local_wifi for pm in peer_macs)) or
                                    bool(local_connected_bssid and local_connected_bssid in peer_macs) or
                                    channel_match_5g
                                )
                                
                                w_info = None
                                for pm in peer_macs:
                                    if pm in local_wifi:
                                        w_info = local_wifi[pm]
                                        break

                                main_ap_mac = mac_5g if mac_5g else peer_src

                                for m in peer_macs:
                                    is_associated_wifi = peer_is_wireless or (m in local_wifi)
                                    if is_associated_wifi:
                                        w_iface = (w_info.get('iface', '') if w_info else '') or local_health.get('iface', '')
                                        if (
                                            m in peer_5g or
                                            m == mac_5g or
                                            '5' in w_iface or
                                            'phy1' in w_iface or
                                            local_connected_bssid == mac_5g or
                                            (local_connected_bssid and local_connected_bssid in peer_5g) or
                                            channel_match_5g
                                        ):
                                            medium = 'وايرليس 5GHz 📶'
                                            medium_type = 'wireless_5g'
                                        else:
                                            medium = 'وايرليس 2.4GHz 📶'
                                            medium_type = 'wireless_2g'
                                        sig = w_info.get("signal") if (w_info and "signal" in w_info) else p_health.get("signal", -60)
                                    else:
                                        medium = 'كابل LAN سلكي 🔌'
                                        medium_type = 'lan'
                                        sig = p_health.get("signal", -60)

                                    band = "5GHz" if (m in peer_5g or m == mac_5g) else ("2.4GHz" if m in peer_2g else "LAN")
                                    peers_db[m] = {
                                        "hostname": peer_host,
                                        "ip": peer_ip,
                                        "band": band,
                                        "medium": medium,
                                        "medium_type": medium_type,
                                        "src_mac": main_ap_mac,
                                        "mac_5g": mac_5g,
                                        "mac_lan": mac_lan or peer_src,
                                        "noise": p_health.get("noise", -90),
                                        "signal": sig,
                                        "channel": p_health.get("channel", 36),
                                        "mode": p_health.get("mode", "ap"),
                                        "connected_bssid": p_health.get("connected_bssid", ""),
                                        "last_seen": now_t,
                                        "is_ap": True
                                    }
                                tmp_p = "/tmp/horus_ap_peers.json.tmp"
                                with open(tmp_p, "w") as f:
                                    json.dump(peers_db, f)
                                os.replace(tmp_p, "/tmp/horus_ap_peers.json")
                                sync_peer_host_hints(peers_db)
                            except Exception:
                                log.exception("peer_announce handling failed")
            except Exception:
                log.exception("listen_loop packet handling failed")

    def handle_anti_spoofing(self, now):
        suspicious_macs = self.db.get_suspicious_clients(self.grace_period, now)
        for cmac in suspicious_macs:
            self.db.ban_client(cmac, 'تكرار ماك وسرقة (MAC Spoofing)', 0, now)
            ban_mac_locally(cmac)
            self.send_cmd({'type': 'ban', 'src_mac': self.my_mac, 'target_mac': cmac, 'duration': 0})

    def process_fast_commands(self):
        now = time.time()

        # 1. Pending Ban Commands
        if os.path.exists(BAN_CMD_FILE):
            try:
                with open(BAN_CMD_FILE, 'r') as f: raw_content = f.read()
                os.remove(BAN_CMD_FILE)
                cmd = json.loads(raw_content)
                action = cmd.get('action')
                cmac = cmd.get('mac', '').upper()
                duration = cmd.get('duration', 0)
                target_aps = cmd.get('target_aps', cmd.get('scope', 'all'))
                
                with self.lock:
                    if action == 'ban':
                        self.db.ban_client(cmac, 'manual', duration, now)
                        if target_aps == 'all' or self.my_mac in target_aps or not target_aps:
                            ban_mac_locally(cmac)
                        if target_aps == 'all':
                            # Network-wide: no single AP to track an ack against,
                            # so this stays a best-effort broadcast (unchanged).
                            self.send_cmd({'type': 'ban', 'src_mac': self.my_mac, 'target_mac': cmac, 'duration': duration})
                        elif isinstance(target_aps, list):
                            for ap_target in target_aps:
                                ap_target = str(ap_target).upper()
                                if ap_target != self.my_mac:
                                    # payload's own 'target_mac' means the CLIENT being
                                    # banned (the ban message schema), NOT the destination
                                    # AP -- the AP we're delivering to is enqueue_cmd's
                                    # own target_mac argument, used purely for routing.
                                    self.db.enqueue_cmd('ban', 'ban', ap_target,
                                        {'type': 'ban', 'src_mac': self.my_mac, 'target_mac': cmac, 'duration': duration})
                    elif action == 'unban':
                        self.db.unban_client(cmac)
                        unban_mac_locally(cmac)
                        self.send_cmd({'type': 'unban', 'src_mac': self.my_mac, 'target_mac': cmac})
            except Exception:
                log.exception("ban/unban command failed")

        # 2. Pending Wi-Fi Commands
        if os.path.exists(WIFI_CMD_FILE):
            try:
                with open(WIFI_CMD_FILE, 'r') as f: raw_content = f.read()
                os.remove(WIFI_CMD_FILE)
                cmd = json.loads(raw_content)
                target_ap = cmd.get('target_aps') or cmd.get('target_ap', '')
                iface = cmd.get('iface', 'wlan0')
                action = cmd.get('action', '')
                value = cmd.get('value', '')
                
                cmd['src_mac'] = self.my_mac
                cmd['type'] = 'wifi_config'
                
                kwargs = {k: v for k, v in cmd.items() if k not in ('action', 'iface', 'value')}
                if isinstance(target_ap, list):
                    for ap in target_ap:
                        ap = str(ap).upper()
                        if ap == self.my_mac:
                            apply_wifi_config(action, iface, value, **kwargs)
                        else:
                            cmd_copy = cmd.copy()
                            cmd_copy['target_mac'] = ap
                            self.db.enqueue_cmd('wifi', action, ap, cmd_copy)
                else:
                    target_ap = str(target_ap).upper()
                    if target_ap == self.my_mac:
                        apply_wifi_config(action, iface, value, **kwargs)
                    elif target_ap == 'ALL':
                        # Applies to every provisioned AP at once -- no single
                        # target to track an ack against, stays best-effort.
                        apply_wifi_config(action, iface, value, **kwargs)
                        cmd['target_mac'] = 'ALL'
                        self.send_cmd(cmd)
                    else:
                        cmd['target_mac'] = target_ap
                        self.db.enqueue_cmd('wifi', action, target_ap, cmd)
            except Exception:
                log.exception("wifi_config command failed")

        # 3. Pending AP Remote Control Commands
        if os.path.exists(AP_CMD_FILE):
            try:
                with open(AP_CMD_FILE, 'r') as f: raw_content = f.read()
                os.remove(AP_CMD_FILE)
                cmd = json.loads(raw_content)
                target_ap = cmd.get('target_aps') or cmd.get('target_ap', '')
                cmd['src_mac'] = self.my_mac
                cmd['type'] = 'ap_manage'

                if cmd.get('action') == 'set_api_key':
                    if not cmd.get('key'):
                        cmd['key'] = self.secret
                    if not cmd.get('key'):
                        log.error("set_api_key requested with no hmp_secret configured -- refusing")
                        return

                if cmd.get('action') == 'delete_ap':
                    ap_m = cmd.get('target_aps') or cmd.get('target_ap', '')
                    targets = ap_m if isinstance(ap_m, list) else [ap_m]
                    for m in targets:
                        m = str(m).upper()
                        if not m:
                            continue
                        self.db.enqueue_cmd('ap', 'unadopt', m, {
                            'type': 'ap_manage',
                            'src_mac': self.my_mac,
                            'target_mac': m,
                            'action': 'unadopt'
                        })
                        self.db.delete_ap(m)
                    return

                if cmd.get("action") in ("admin_password", "bulk_admin_password", "set_root_password"):
                    new_pw = cmd.get("password")
                    is_target = (target_ap == "ALL" or (isinstance(target_ap, list) and self.my_mac in target_ap) or target_ap == self.my_mac)
                    if new_pw and is_target and isinstance(new_pw, str) and len(new_pw) <= 64:
                        proc = subprocess.Popen(["passwd", "root"], stdin=subprocess.PIPE)
                        proc.communicate(input=f"{new_pw}\n{new_pw}\n".encode())

                if cmd.get("action") in ("port_state", "port_toggle"):
                    target_p = cmd.get("port")
                    n_state = cmd.get("state")
                    is_target = (target_ap == "ALL" or (isinstance(target_ap, list) and self.my_mac in target_ap) or target_ap == self.my_mac)
                    if is_target and target_p and n_state in ['up', 'down']:
                        try:
                            if n_state == 'down':
                                subprocess.run(f"ip link set {target_p} down 2>/dev/null", shell=True)
                                subprocess.run(f"ip link set {target_p} nomaster 2>/dev/null", shell=True)
                                subprocess.run(f"brctl delif br-lan {target_p} 2>/dev/null", shell=True)
                                try:
                                    p_num = ''.join(c for c in target_p if c.isdigit())
                                    if p_num:
                                        subprocess.run(f"swconfig dev switch0 port {p_num} set disable 1 2>/dev/null; swconfig dev switch0 set apply 2>/dev/null", shell=True)
                                except Exception:
                                    pass
                            else:
                                subprocess.run(f"ip link set {target_p} master br-lan 2>/dev/null", shell=True)
                                subprocess.run(f"brctl addif br-lan {target_p} 2>/dev/null", shell=True)
                                subprocess.run(f"ip link set {target_p} up 2>/dev/null", shell=True)
                                try:
                                    p_num = ''.join(c for c in target_p if c.isdigit())
                                    if p_num:
                                        subprocess.run(f"swconfig dev switch0 port {p_num} set disable 0 2>/dev/null; swconfig dev switch0 set apply 2>/dev/null", shell=True)
                                except Exception:
                                    pass
                        except Exception:
                            log.exception("local port_state failed")

                if cmd.get('action') == 'set_api_key':
                    if isinstance(target_ap, str) and target_ap != 'ALL':
                        self.db.set_ap_authorized(target_ap, authorized=True)

                if cmd.get('action') == 'set_hostname':
                    new_hname = cmd.get('hostname')
                    if new_hname and isinstance(target_ap, str) and target_ap in self.db.state.get('aps', {}):
                        self.db.state['aps'][target_ap]['hostname'] = new_hname
                        self.db.save()
                elif cmd.get('action') == 'set_ip':
                    new_ip = cmd.get('ip')
                    new_hname = cmd.get('hostname')
                    if isinstance(target_ap, str) and target_ap in self.db.state.get('aps', {}):
                        if new_ip: self.db.state['aps'][target_ap]['ip'] = new_ip
                        if new_hname: self.db.state['aps'][target_ap]['hostname'] = new_hname
                        self.db.save()

                if cmd.get('action') == 'install_package':
                    pkg = cmd.get('package', '')
                    t_list = target_ap if isinstance(target_ap, list) else ([target_ap] if target_ap != 'ALL' else list(self.db.state.get('aps', {}).keys()))
                    try:
                        st_record = {
                            "package": pkg,
                            "ts": int(time.time()),
                            "targets": {}
                        }
                        for m in t_list:
                            m_up = str(m).upper()
                            st_record["targets"][m_up] = {
                                "status": "installing",
                                "message": "جاري التحميل والتثبيت على الجهاز...",
                                "ts": int(time.time())
                            }
                        with open("/tmp/horus_pkg_status.json", "w") as sf:
                            json.dump(st_record, sf)
                    except Exception:
                        pass
                    
                    if self.my_mac in [str(x).upper() for x in t_list] or target_ap == 'ALL':
                        def _install_local(p):
                            succ = False
                            emsg = ""
                            if p.startswith("http"):
                                try:
                                    cmd_fetch = f"uclient-fetch -q -T 30 -O /tmp/pkg_local.ipk '{p}' || wget -q -T 30 -O /tmp/pkg_local.ipk '{p}' || curl -s -m 30 -o /tmp/pkg_local.ipk '{p}'"
                                    subprocess.run(cmd_fetch, shell=True)
                                    inst = subprocess.run("opkg install /tmp/pkg_local.ipk --force-overwrite", shell=True, capture_output=True, text=True)
                                    succ = (inst.returncode == 0)
                                    emsg = "تم التثبيت بنجاح على الكنترولر" if succ else (inst.stderr or inst.stdout or "فشل التثبيت")
                                except Exception as e:
                                    emsg = str(e)
                            else:
                                inst = subprocess.run(f"opkg install {p}", shell=True, capture_output=True, text=True)
                                succ = (inst.returncode == 0)
                                emsg = "تم التثبيت بنجاح على الكنترولر" if succ else (inst.stderr or inst.stdout or "فشل التثبيت")
                            try:
                                with open("/tmp/horus_pkg_status.json", "r") as sf:
                                    cur_st = json.load(sf)
                                if "targets" in cur_st:
                                    cur_st["targets"][self.my_mac] = {
                                        "status": "success" if succ else "error",
                                        "message": emsg,
                                        "package": p,
                                        "ts": int(time.time())
                                    }
                                    with open("/tmp/horus_pkg_status.json", "w") as sf:
                                        json.dump(cur_st, sf)
                            except Exception:
                                pass
                        threading.Thread(target=_install_local, args=(pkg,)).start()

                if isinstance(target_ap, list):
                    for ap in target_ap:
                        ap = str(ap).upper()
                        if ap != self.my_mac:
                            cmd_copy = cmd.copy()
                            cmd_copy['target_mac'] = ap
                            rescue_sec = (ap + "_horus_rescue") if cmd.get('action') == 'set_api_key' else None
                            self.db.enqueue_cmd('ap', cmd.get('action', ''), ap, cmd_copy, rescue_secret=rescue_sec)
                        elif cmd.get('action') == 'reboot':
                            threading.Thread(target=lambda: (time.sleep(2), subprocess.run("reboot", shell=True))).start()
                else:
                    target_ap = str(target_ap).upper()
                    if target_ap == 'ALL':
                        cmd['target_mac'] = 'ALL'
                        self.send_cmd(cmd, dst_mac='FF:FF:FF:FF:FF:FF')
                    elif target_ap:
                        if target_ap != self.my_mac:
                            cmd['target_mac'] = target_ap
                            rescue_sec = (target_ap + "_horus_rescue") if cmd.get('action') == 'set_api_key' else None
                            self.db.enqueue_cmd('ap', cmd.get('action', ''), target_ap, cmd, rescue_secret=rescue_sec)
                        elif cmd.get('action') == 'reboot':
                            threading.Thread(target=lambda: (time.sleep(2), subprocess.run("reboot", shell=True))).start()
            except Exception:
                log.exception("ap_manage command failed")

    def dispatch_queue(self):
        """Send (or retry) every command in the queue that needs a frame sent
        right now. Actual delivery confirmation comes back asynchronously as
        a 'cmd_ack' message, handled in listen_loop()."""
        now = time.time()
        with self.lock:
            due = self.db.cmd_due_for_send(now)
        for entry in due:
            payload = dict(entry["payload"])
            payload["cmd_id"] = entry["id"]
            dst = entry["target_mac"]
            self.send_cmd(payload, dst_mac=dst)
            if entry.get("rescue_secret"):
                self.send_cmd(payload, dst_mac=dst, secret=entry["rescue_secret"])
            with self.lock:
                self.db.mark_cmd_sent(entry["id"])

    def fast_cmd_loop(self):
        while True:
            try:
                self.process_fast_commands()
                self.dispatch_queue()
            except Exception:
                log.exception("fast_cmd_loop iteration failed")
            time.sleep(0.2)

    def maintenance_loop(self):
        # NOTE: pending UI commands (ban/wifi/ap files) are handled exclusively
        # by fast_cmd_loop() running in its own thread (see core.py). Calling
        # process_fast_commands() from here too would let both threads read and
        # os.remove() the same command file concurrently, corrupting or double-
        # firing commands.
        loop_tick = 0
        while True:
            try:
                time.sleep(1)
                now = time.time()
                loop_tick += 1

                # 1. Gather all local data OUTSIDE the lock
                own_clients = get_wireless_macs()
                my_hostname = get_hostname()
                my_ip = get_lan_ip()
                my_wifi = get_wifi_info()
                my_scan = {}
                my_ports = get_ethernet_ports()
                my_stats = get_system_stats()

                # 2. In-memory DB writes
                with self.lock:
                    self.db.update_ap(
                        mac=self.my_mac,
                        hostname=my_hostname,
                        ip=my_ip,
                        last_seen=now,
                        wifi_info=my_wifi,
                        scan_data=my_scan,
                        ports=my_ports,
                        stats=my_stats,
                        netmask=get_lan_netmask(),
                        gateway=get_lan_gateway(),
                        radio_macs=get_wifi_radios_and_macs().get('all', [])
                    )
                    self.db.update_clients(self.my_mac, own_clients, now)
                    self.handle_anti_spoofing(now)
                    unbanned_macs = self.db.cleanup_stale(AP_DEAD_TIMEOUT, 60, now)
                    self.db.cleanup_foreign_aps(AP_DEAD_TIMEOUT, now)
                    self.db.snapshot_if_due(now)
                    if loop_tick % 5 == 0:
                        self.db.compute_topology()

                # Broadcast Layer 2 Root Heartbeat frame across the network.
                # This is a DISCOVERY BEACON ("a controller exists here"), not a
                # per-AP status report: it is addressed to ALL, so it carries no
                # is_authorized claim. Only the targeted ACK sent from
                # listen_loop() knows whether a specific AP is adopted, and the
                # satellite deliberately does not let this beacon overwrite that
                # -- otherwise an unadopted AP would flip between
                # "awaiting_activation" and "online" every few seconds.
                if loop_tick % 5 == 0:
                    self.send_cmd({
                        'type': 'root_heartbeat',
                        'src_mac': self.my_mac,
                        'target_mac': 'ALL',
                        'root_ip': my_ip,
                        'root_hostname': my_hostname,
                        'ts': now
                    }, dst_mac='FF:FF:FF:FF:FF:FF')

                for cmac in unbanned_macs:
                    unban_mac_locally(cmac)
                    self.send_cmd({'type': 'unban', 'src_mac': self.my_mac, 'target_mac': cmac})

                # 4. Auto-Channel (RRM) every 60s
                self.rrm_counter += 1
                if self.rrm_counter >= 60:
                    self.rrm_counter = 0
                    auto_2g = get_uci('horus_controller.main.auto_ch_2g', '0')
                    auto_5g = get_uci('horus_controller.main.auto_ch_5g', '0')
                    
                    if auto_2g == '1' or auto_5g == '1':
                        with self.lock:
                            full_state = self.db.get_all_state()
                            for ap_mac, ap_data in full_state['aps'].items():
                                scan = ap_data.get('scan_data', {})
                                wifi_list = ap_data.get('wifi', [])
                                for wifi in wifi_list:
                                    ch_str = str(wifi.get('channel', '0'))
                                    try: current_ch = int(ch_str)
                                    except: current_ch = 0
                                    
                                    is_2g = 0 < current_ch <= 14
                                    is_5g = current_ch >= 36
                                    
                                    if (is_2g and auto_2g == '1') or (is_5g and auto_5g == '1'):
                                        allowed = [1, 6, 11] if is_2g else [36, 40, 44, 48, 149, 153, 157, 161]
                                        best_ch = allowed[0]
                                        min_inf = 9999
                                        for c in allowed:
                                            inf = scan.get(str(c), 0)
                                            if inf < min_inf:
                                                min_inf = inf
                                                best_ch = c
                                                
                                        if best_ch != current_ch and current_ch in allowed:
                                            if ap_mac == self.my_mac:
                                                apply_wifi_config('set_channel', wifi['iface'], str(best_ch))
                                            else:
                                                self.db.enqueue_cmd('wifi', 'set_channel', ap_mac, {
                                                    'type': 'wifi_config',
                                                    'src_mac': self.my_mac,
                                                    'target_mac': ap_mac,
                                                    'iface': wifi['iface'],
                                                    'action': 'set_channel',
                                                    'value': str(best_ch)
                                                })

                # 5. Smart Roaming & Min-RSSI Steering (Every 5 seconds)
                if loop_tick % 5 == 0:
                    roaming_en = get_uci('horus_controller.main.roaming_enabled', '1')
                    if roaming_en == '1':
                        try:
                            min_rssi = int(get_uci('horus_controller.main.min_rssi', '-75'))
                        except Exception:
                            min_rssi = -75

                        steer_actions = []
                        with self.lock:
                            all_clients = self.db.get_all_state().get('clients', {})
                            for cmac, cinfo in all_clients.items():
                                if cinfo.get('banned'): continue
                                cur_sig = cinfo.get('signal', -100)
                                cur_ap = cinfo.get('ap_mac', '')

                                if cur_sig < min_rssi and cur_sig > -100:
                                    last_steer = cinfo.get('last_steer_time', 0)
                                    if (now - last_steer) > 15:
                                        cinfo['last_steer_time'] = now
                                        steer_actions.append((cmac, cur_ap, cur_sig))
                                        self.db.add_log('steer', cmac, f'توجيه ذكي ({cur_sig} dBm)', now)

                        for cmac, cur_ap, cur_sig in steer_actions:
                            if cur_ap == self.my_mac:
                                steer_client_locally(cmac, ban_time=3000)
                            else:
                                self.send_cmd({
                                    'type': 'ap_manage',
                                    'src_mac': self.my_mac,
                                    'target_mac': cur_ap,
                                    'action': 'steer_client',
                                    'mac': cmac,
                                    'ban_time': 3000
                                }, dst_mac=cur_ap)

            except Exception:
                log.exception("maintenance_loop iteration failed")
