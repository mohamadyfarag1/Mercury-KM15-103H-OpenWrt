# -*- coding: utf-8 -*-
import os
import re
import json
import time
import subprocess
import threading
from .protocol import send_hmp_frame
from .system import (
    ban_mac_locally, unban_mac_locally, apply_wifi_config,
    steer_client_locally, enable_80211kv_locally, request_wifi_reload
)

from .logutil import get_logger
log = get_logger("horus.sat_actions")

def _sanitize_value(val, pattern=r'^[\w\.\-\:/\@ ]+$', max_len=128):
    """Sanitize network-received values before shell use."""
    if not val or not isinstance(val, str):
        return None
    val = val.strip()
    if len(val) > max_len:
        return None
    if not re.match(pattern, val):
        return None
    return val

def _sanitize_ip(val):
    return _sanitize_value(val, pattern=r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', max_len=15)

def _sanitize_mac(val):
    return _sanitize_value(val, pattern=r'^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$', max_len=17)

def _sanitize_hostname(val):
    if not val or not isinstance(val, str):
        return None
    val = val.strip()
    if not val or len(val) > 128:
        return None
    if re.search(r'[;&`\'"\$\n\r<>|]', val):
        return None
    return val

def _sanitize_port(val):
    return _sanitize_value(val, pattern=r'^[\w\-\.]+$', max_len=32)

def _sanitize_int(val):
    try:
        return str(int(val))
    except (ValueError, TypeError):
        return None


def execute_ban_unban(node, data, msg_type):
    """Handle ban / unban commands from controller."""
    # _sanitize_mac returns None for a malformed MAC; calling .upper() on that
    # threw AttributeError and aborted the whole packet (no ack was sent).
    target_client = _sanitize_mac(data.get("target_mac", ""))
    if not target_client:
        return
    target_client = target_client.upper()
    if msg_type == "ban":
        ban_mac_locally(target_client)
    elif msg_type == "unban":
        unban_mac_locally(target_client)

def execute_wifi_config(node, data):
    """Handle wifi_config actions from controller."""
    action = data.get("action")
    iface = data.get("iface", "ALL")
    value = data.get("value", "")
    if action:
        kwargs = {k: v for k, v in data.items() if k not in ("action", "iface", "value")}
        apply_wifi_config(action, iface, value, **kwargs)

def execute_ap_manage(node, data, ack_secret):
    """Execute AP hardware remote control commands from controller."""
    action = data.get("action")
    
    if action in ("network", "set_ip"):
        ip = _sanitize_ip(data.get("ip"))
        netmask = _sanitize_ip(data.get("netmask"))
        gateway = _sanitize_ip(data.get("gateway"))
        hname = _sanitize_hostname(data.get("hostname"))
        
        try:
            cur_ip = subprocess.check_output("uci -q get network.lan.ipaddr", shell=True, text=True).strip()
        except Exception:
            cur_ip = ""
        try:
            cur_mask = subprocess.check_output("uci -q get network.lan.netmask", shell=True, text=True).strip()
        except Exception:
            cur_mask = ""
        try:
            cur_gw = subprocess.check_output("uci -q get network.lan.gateway", shell=True, text=True).strip()
        except Exception:
            cur_gw = ""
        
        changed_network = False
        if ip and ip != "0.0.0.0" and ip != cur_ip:
            subprocess.run(f"uci set network.lan.ipaddr='{ip}'", shell=True)
            changed_network = True
        if netmask and netmask != cur_mask:
            subprocess.run(f"uci set network.lan.netmask='{netmask}'", shell=True)
            changed_network = True
        if gateway and gateway != cur_gw:
            subprocess.run(f"uci set network.lan.gateway='{gateway}'", shell=True)
            changed_network = True
            
        if changed_network:
            subprocess.run("uci commit network", shell=True)
            threading.Thread(target=lambda: (time.sleep(2), subprocess.run("/etc/init.d/network restart", shell=True))).start()
            
        if hname:
            safe_hname = hname.replace("'", "")
            try:
                cur_hname = subprocess.check_output("uci -q get system.@system[0].hostname", shell=True, text=True).strip()
            except Exception:
                cur_hname = ""
            if safe_hname != cur_hname:
                subprocess.run(f"uci set system.@system[0].hostname='{safe_hname}'", shell=True)
                subprocess.run("uci commit system", shell=True)
                subprocess.run(f"echo '{safe_hname}' > /proc/sys/kernel/hostname", shell=True)
                subprocess.run("/etc/init.d/system reload", shell=True)
    
    elif action == "reboot":
        threading.Thread(target=lambda: (time.sleep(2), subprocess.run("reboot", shell=True))).start()
    
    elif action == "install_package":
        pkg = data.get("package", "")
        cmd_id = data.get("cmd_id", "")
        if pkg:
            def _install(p, cid):
                success = False
                err_msg = ""
                if p.startswith("http"):
                    try:
                        cmd = f"uclient-fetch -q -T 30 -O /tmp/pkg.ipk '{p}' || wget -q -T 30 -O /tmp/pkg.ipk '{p}' || curl -s -m 30 -o /tmp/pkg.ipk '{p}'"
                        res = subprocess.run(cmd, shell=True)
                        if res.returncode == 0 and os.path.exists("/tmp/pkg.ipk"):
                            inst = subprocess.run("opkg install /tmp/pkg.ipk --force-overwrite", shell=True, capture_output=True, text=True)
                            if inst.returncode == 0:
                                success = True
                                err_msg = "تم التثبيت بنجاح"
                            else:
                                err_msg = inst.stderr or inst.stdout or "فشل التثبيت"
                        else:
                            err_msg = "فشل تحميل ملف الحزمة من الكنترولر"
                    except Exception as e:
                        err_msg = str(e)
                else:
                    p_safe = _sanitize_value(p, pattern=r'^[\w\-\.]+$', max_len=64)
                    if p_safe:
                        subprocess.run("opkg update >/dev/null 2>&1", shell=True)
                        inst = subprocess.run(f"opkg install {p_safe}", shell=True, capture_output=True, text=True)
                        if inst.returncode == 0:
                            success = True
                            err_msg = "تم التثبيت بنجاح"
                        else:
                            err_msg = inst.stderr or inst.stdout or "فشل التثبيت"
                
                try:
                    node.send_to_root({
                        "type": "pkg_install_result",
                        "src_mac": node.my_mac,
                        "cmd_id": cid,
                        "package": p,
                        "success": success,
                        "message": err_msg
                    })
                except Exception:
                    pass

            threading.Thread(target=_install, args=(pkg, cmd_id)).start()
    
    elif action == "kick":
        cmac = _sanitize_mac(data.get("mac", ""))
        if cmac:
            try:
                out = subprocess.check_output("ubus list | grep hostapd", shell=True, text=True)
                for h in out.splitlines():
                    h = h.strip()
                    if h.startswith("hostapd."):
                        del_arg = json.dumps({"addr": cmac})
                        subprocess.run(f"ubus call {h} del_client '{del_arg}'", shell=True)
            except Exception:
                pass
    
    elif action == "tx_power":
        power = _sanitize_int(data.get("txpower") or data.get("value"))
        if power:
            try:
                out = subprocess.check_output("uci -q show wireless", shell=True, text=True)
                for line in out.splitlines():
                    if "wifi-device" in line:
                        dev = line.split('.')[1].split('=')[0]
                        subprocess.run(f"uci set wireless.{dev}.txpower='{power}'", shell=True)
                subprocess.run("uci commit wireless", shell=True)
                request_wifi_reload()
            except Exception:
                pass
    
    elif action == "set_hostname":
        hname = _sanitize_hostname(data.get("hostname"))
        if hname:
            try:
                safe_hname = hname.replace("'", "")
                cur_hname = subprocess.check_output("uci -q get system.@system[0].hostname", shell=True, text=True).strip()
                if safe_hname != cur_hname:
                    subprocess.run(f"uci set system.@system[0].hostname='{safe_hname}'", shell=True)
                    subprocess.run("uci commit system", shell=True)
                    subprocess.run(f"echo '{safe_hname}' > /proc/sys/kernel/hostname", shell=True)
                    subprocess.run("/etc/init.d/system reload", shell=True)
                    node.my_hostname = safe_hname
                    threading.Thread(target=lambda: (time.sleep(0.5), node.send_hello_once())).start()
            except Exception:
                log.exception("set_hostname failed")
    
    elif action in ("wifi_radio", "radio_toggle"):
        target_radio = _sanitize_value(data.get("radio", "all"), pattern=r'^[\w]+$', max_len=16) or "all"
        state = _sanitize_int(data.get("state", "0")) or "0"
        try:
            out = subprocess.check_output("uci -q show wireless", shell=True, text=True)
            devs = [l.split('.')[1].split('=')[0] for l in out.splitlines() if 'wifi-device' in l]
            for dev in devs:
                is_2g = ('0' in dev or '2g' in dev)
                is_5g = ('1' in dev or '5g' in dev)
                match = False
                if target_radio in [dev, 'all', 'both', None]: match = True
                elif target_radio in ['2g', 'radio0'] and is_2g: match = True
                elif target_radio in ['5g', 'radio1'] and is_5g: match = True
                if match:
                    subprocess.run(f"uci set wireless.{dev}.disabled='{state}'", shell=True)
            subprocess.run("uci commit wireless", shell=True)
            request_wifi_reload()
        except Exception:
            pass
    
    elif action == "radio_restart":
        target_radio = _sanitize_value(data.get("radio", "all"), pattern=r'^[\w]+$', max_len=16) or "all"
        request_wifi_reload(target_radio if target_radio != "all" else None)
    
    elif action in ("admin_password", "bulk_admin_password", "set_root_password"):
        new_pw = data.get("password")
        if new_pw and isinstance(new_pw, str) and len(new_pw) <= 64:
            try:
                proc = subprocess.Popen(["passwd", "root"], stdin=subprocess.PIPE)
                proc.communicate(input=f"{new_pw}\n{new_pw}\n".encode())
            except Exception:
                pass

    elif action == "set_api_key":
        new_key = data.get("key")
        if new_key is not None:
            new_key_str = str(new_key).strip()
            if not re.search(r"[';`$\"]", new_key_str) and len(new_key_str) <= 128:
                try:
                    subprocess.run(f"uci set horus_controller.main.hmp_secret='{new_key_str}'", shell=True)
                    adopting_mac = _sanitize_mac(str(data.get("src_mac", "")))
                    if adopting_mac:
                        adopting_mac = adopting_mac.upper()
                        subprocess.run(
                            f"uci set horus_controller.main.controller_mac='{adopting_mac}'", shell=True)
                        node.controller_mac = adopting_mac
                    subprocess.run("uci commit horus_controller", shell=True)
                    node.secret = new_key_str
                    threading.Thread(target=lambda: (time.sleep(0.5), node.send_hello_once(), node.send_telemetry_once())).start()
                except Exception:
                    log.exception("set_api_key failed")

    elif action in ("unadopt", "forget", "delete_node"):
        node.unadopt("controller sent unadopt")
    
    elif action == "steer_client":
        target_mac = data.get("mac")
        target_bssid = data.get("target_bssid")
        ban_time = data.get("ban_time", 3000)
        if target_mac:
            steer_client_locally(target_mac, target_bssid=target_bssid, ban_time=ban_time)
    
    elif action == "enable_80211kv":
        enable_80211kv_locally()
    
    elif action in ("port_state", "port_toggle"):
        port = _sanitize_port(data.get("port"))
        state = data.get("state")
        if port and state in ['up', 'down']:
            try:
                if state == 'down':
                    subprocess.run(f"ip link set {port} down 2>/dev/null", shell=True)
                    subprocess.run(f"ip link set {port} nomaster 2>/dev/null", shell=True)
                    subprocess.run(f"brctl delif br-lan {port} 2>/dev/null", shell=True)
                    try:
                        p_num = ''.join(c for c in port if c.isdigit())
                        if p_num:
                            subprocess.run(f"swconfig dev switch0 port {p_num} set disable 1 2>/dev/null; swconfig dev switch0 set apply 2>/dev/null", shell=True)
                    except Exception:
                        pass
                else:
                    subprocess.run(f"ip link set {port} master br-lan 2>/dev/null", shell=True)
                    subprocess.run(f"brctl addif br-lan {port} 2>/dev/null", shell=True)
                    subprocess.run(f"ip link set {port} up 2>/dev/null", shell=True)
                    try:
                        p_num = ''.join(c for c in port if c.isdigit())
                        if p_num:
                            subprocess.run(f"swconfig dev switch0 port {p_num} set disable 0 2>/dev/null; swconfig dev switch0 set apply 2>/dev/null", shell=True)
                    except Exception:
                        pass
            except Exception:
                log.exception("port_state command failed")

def send_cmd_ack(node, data, ack_secret):
    """Acknowledge command delivery back to controller."""
    cmd_id = data.get("cmd_id")
    msg_type = data.get("type")
    if cmd_id and msg_type in ("ban", "unban", "wifi_config", "ap_manage"):
        try:
            send_hmp_frame(node.raw_sock, node.udp_sock, {
                "type": "cmd_ack",
                "src_mac": node.my_mac,
                "target_mac": data.get("src_mac", "").upper(),
                "cmd_id": cmd_id,
                "ok": True
            }, dst_mac="FF:FF:FF:FF:FF:FF", dst_ip=node.controller_ip, secret=ack_secret)
        except Exception:
            log.exception("cmd_ack send failed")
