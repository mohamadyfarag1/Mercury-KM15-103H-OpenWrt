# -*- coding: utf-8 -*-
import os
import subprocess
import time
import json
import re
import threading
from .sys_utils import format_speed, format_bytes, OUI_MAP
from .logutil import get_logger

log = get_logger("horus.sys_wifi")

PREV_CLIENT_STATS = {}

# --- Coalesced `wifi reload` -------------------------------------------------
# A `wifi reload` tears down and rebuilds the radios, briefly dropping every
# associated client. A burst of commands from the controller (e.g. set channel,
# then SSID, then tx-power) used to trigger one reload EACH -- clients dropped
# several times in a row. This coalesces reloads inside a short quiet window:
# many requests within `delay` seconds collapse into a single reload, and a
# request that targets specific radios only reloads those (no full-radio hit
# for a single-radio change) unless a full reload was also requested.
_reload_lock = threading.Lock()
_reload_state = {"timer": None, "full": False, "targets": set()}


def _fire_wifi_reload():
    with _reload_lock:
        full = _reload_state["full"] or not _reload_state["targets"]
        targets = set(_reload_state["targets"])
        _reload_state["full"] = False
        _reload_state["targets"] = set()
        _reload_state["timer"] = None
    try:
        if full:
            subprocess.run(["wifi", "reload"])
        else:
            for radio in targets:
                subprocess.run(["wifi", "reload", radio])
    except Exception:
        log.exception("wifi reload failed")


def request_wifi_reload(radio=None, delay=1.5):
    """Schedule a (debounced) `wifi reload`, coalescing rapid bursts."""
    with _reload_lock:
        if radio in (None, "", "all", "both"):
            _reload_state["full"] = True
        else:
            _reload_state["targets"].add(str(radio))
        if _reload_state["timer"] is not None:
            _reload_state["timer"].cancel()
        t = threading.Timer(delay, _fire_wifi_reload)
        t.daemon = True
        _reload_state["timer"] = t
        t.start()

def get_wireless_macs():
    global PREV_CLIENT_STATS
    now = time.time()
    clients = []
    seen_macs = set()

    # 1. Primary: Query hostapd ubus for deep stats (rx_bytes, tx_bytes, rate, signal)
    try:
        out = subprocess.check_output("ubus list | grep hostapd", shell=True, text=True)
        for h in out.splitlines():
            h = h.strip()
            if not h or not h.startswith("hostapd."): continue
            iface_name = h.replace("hostapd.", "")
            try:
                raw = subprocess.check_output(f"ubus call {h} get_clients", shell=True, text=True)
                data = json.loads(raw)
                cl_dict = data.get("clients", {})
                for mac_str, info in cl_dict.items():
                    mac = mac_str.upper()
                    seen_macs.add(mac)
                    sig = info.get("signal", -100)
                    rx_b = info.get("bytes", {}).get("rx", 0)
                    tx_b = info.get("bytes", {}).get("tx", 0)
                    rate_tx = info.get("rate", {}).get("tx", 0)

                    rx_speed_bps = 0
                    tx_speed_bps = 0
                    if mac in PREV_CLIENT_STATS:
                        dt = now - PREV_CLIENT_STATS[mac]["ts"]
                        if dt > 0.5:
                            rx_speed_bps = max(0, rx_b - PREV_CLIENT_STATS[mac]["rx"]) * 8 / dt
                            tx_speed_bps = max(0, tx_b - PREV_CLIENT_STATS[mac]["tx"]) * 8 / dt
                    PREV_CLIENT_STATS[mac] = {"rx": rx_b, "tx": tx_b, "ts": now}
                    
                    oui = mac[:8]
                    vendor_name, vendor_icon = OUI_MAP.get(oui, ("جهاز غير معروف", "📱"))
                    if len(mac) >= 2 and mac[1].upper() in ['2', '6', 'A', 'E']:
                        vendor_name, vendor_icon = ("ماك عشوائي (Private MAC)", "🔒")

                    clients.append({
                        "mac": mac,
                        "signal": sig,
                        "iface": iface_name,
                        "vendor": vendor_name,
                        "vendor_icon": vendor_icon,
                        "rx_speed": format_speed(rx_speed_bps),
                        "tx_speed": format_speed(tx_speed_bps),
                        "rx_speed_bps": int(rx_speed_bps),
                        "tx_speed_bps": int(tx_speed_bps),
                        "total_rx": format_bytes(rx_b),
                        "total_tx": format_bytes(tx_b),
                        "link_rate": format_speed(rate_tx) if rate_tx > 0 else "-"
                    })
            except Exception:
                pass
    except Exception:
        pass

    # 2. Multi-Radio & Fallback Sweep: Check all interfaces via iwinfo and iw dev
    # (Guarantees gathering 5GHz clients, STA mode stations, and interfaces where hostapd ubus is omitted)
    try:
        all_wifi_ifaces = set()
        try:
            for dev in os.listdir("/sys/class/net"):
                if os.path.exists(f"/sys/class/net/{dev}/phy80211") or os.path.exists(f"/sys/class/net/{dev}/wireless"):
                    all_wifi_ifaces.add(dev)
        except Exception:
            pass
        try:
            iw_out = subprocess.check_output("iwinfo | grep -E '^[a-zA-Z0-9_-]+'", shell=True, text=True)
            for line in iw_out.splitlines():
                if line.strip():
                    all_wifi_ifaces.add(line.split()[0])
        except Exception:
            pass
        try:
            iw_d = subprocess.check_output("iw dev 2>/dev/null", shell=True, text=True)
            for line in iw_d.splitlines():
                line = line.strip()
                if line.startswith("Interface "):
                    all_wifi_ifaces.add(line.split()[1])
        except Exception:
            pass

        for iface in all_wifi_ifaces:
            # Check if this interface is in STA / client / managed mode (connected to upstream AP)
            try:
                link_out = subprocess.check_output(f"iw dev {iface} link 2>/dev/null", shell=True, text=True)
                m_link = re.search(r"Connected to\s+([0-9A-Fa-f:]{17})", link_out, re.IGNORECASE)
                if m_link:
                    bssid = m_link.group(1).upper()
                    if bssid not in seen_macs and bssid != "00:00:00:00:00:00":
                        seen_macs.add(bssid)
                        sig = -60
                        m_sig = re.search(r"signal:\s*(-?\d+)", link_out)
                        if m_sig:
                            sig = int(m_sig.group(1))
                        clients.append({
                            "mac": bssid,
                            "signal": sig,
                            "iface": iface,
                            "vendor": "Horus AP",
                            "vendor_icon": "📡",
                            "rx_speed": "-",
                            "tx_speed": "-",
                            "rx_speed_bps": 0,
                            "tx_speed_bps": 0,
                            "total_rx": "-",
                            "total_tx": "-",
                            "link_rate": "-"
                        })
            except Exception:
                pass

            try:
                dev_info = subprocess.check_output(f"iw dev {iface} info 2>/dev/null", shell=True, text=True)
                if "type managed" in dev_info:
                    continue
            except Exception:
                pass

            # 2a. Query iw dev <iface> station dump (PRIMARY: has tx/rx bytes)
            try:
                st_dump = subprocess.check_output(f"iw dev {iface} station dump 2>/dev/null", shell=True, text=True)
                cur_station_mac = None
                cur_sig = -70
                cur_rx_b = 0
                cur_tx_b = 0
                cur_rate = "-"
                for line in st_dump.splitlines():
                    line = line.strip()
                    if line.startswith("Station "):
                        if cur_station_mac and cur_station_mac not in seen_macs:
                            seen_macs.add(cur_station_mac)
                            oui = cur_station_mac[:8]
                            vendor_name, vendor_icon = OUI_MAP.get(oui, ("", ""))
                            if len(cur_station_mac) >= 2 and cur_station_mac[1].upper() in ['2', '6', 'A', 'E']:
                                vendor_name, vendor_icon = ("ماك عشوائي (Private MAC)", "🔒")
                            
                            rx_speed_bps = 0
                            tx_speed_bps = 0
                            if cur_rx_b > 0 or cur_tx_b > 0:
                                if cur_station_mac in PREV_CLIENT_STATS:
                                    dt = now - PREV_CLIENT_STATS[cur_station_mac]["ts"]
                                    if dt > 0.5:
                                        rx_speed_bps = max(0, cur_rx_b - PREV_CLIENT_STATS[cur_station_mac]["rx"]) * 8 / dt
                                        tx_speed_bps = max(0, cur_tx_b - PREV_CLIENT_STATS[cur_station_mac]["tx"]) * 8 / dt
                                PREV_CLIENT_STATS[cur_station_mac] = {"rx": cur_rx_b, "tx": cur_tx_b, "ts": now}

                            clients.append({
                                "mac": cur_station_mac,
                                "signal": cur_sig,
                                "iface": iface,
                                "vendor": vendor_name,
                                "vendor_icon": vendor_icon,
                                "rx_speed": format_speed(rx_speed_bps),
                                "tx_speed": format_speed(tx_speed_bps),
                                "rx_speed_bps": int(rx_speed_bps),
                                "tx_speed_bps": int(tx_speed_bps),
                                "total_rx": format_bytes(cur_rx_b) if cur_rx_b > 0 else "-",
                                "total_tx": format_bytes(cur_tx_b) if cur_tx_b > 0 else "-",
                                "link_rate": cur_rate
                            })

                        parts = line.split()
                        if len(parts) >= 2:
                            smac = parts[1].upper()
                            if len(smac) == 17 and smac.count(':') == 5:
                                cur_station_mac = smac
                                cur_sig = -70
                                cur_rx_b = 0
                                cur_tx_b = 0
                                cur_rate = "-"
                    elif cur_station_mac:
                        if "signal:" in line:
                            try:
                                cur_sig = int(line.split("signal:")[1].split()[0].replace("dBm", ""))
                            except: pass
                        elif "rx bytes:" in line:
                            try: cur_rx_b = int(line.split("rx bytes:")[1].split()[0])
                            except: pass
                        elif "tx bytes:" in line:
                            try: cur_tx_b = int(line.split("tx bytes:")[1].split()[0])
                            except: pass
                        elif "tx bitrate:" in line:
                            try: cur_rate = line.split("tx bitrate:")[1].strip().split(",")[0]
                            except: pass

                if cur_station_mac and cur_station_mac not in seen_macs:
                    seen_macs.add(cur_station_mac)
                    oui = cur_station_mac[:8]
                    vendor_name, vendor_icon = OUI_MAP.get(oui, ("", ""))
                    if len(cur_station_mac) >= 2 and cur_station_mac[1].upper() in ['2', '6', 'A', 'E']:
                        vendor_name, vendor_icon = ("ماك عشوائي (Private MAC)", "🔒")
                    
                    rx_speed_bps = 0
                    tx_speed_bps = 0
                    if cur_rx_b > 0 or cur_tx_b > 0:
                        if cur_station_mac in PREV_CLIENT_STATS:
                            dt = now - PREV_CLIENT_STATS[cur_station_mac]["ts"]
                            if dt > 0.5:
                                rx_speed_bps = max(0, cur_rx_b - PREV_CLIENT_STATS[cur_station_mac]["rx"]) * 8 / dt
                                tx_speed_bps = max(0, cur_tx_b - PREV_CLIENT_STATS[cur_station_mac]["tx"]) * 8 / dt
                        PREV_CLIENT_STATS[cur_station_mac] = {"rx": cur_rx_b, "tx": cur_tx_b, "ts": now}

                    clients.append({
                        "mac": cur_station_mac,
                        "signal": cur_sig,
                        "iface": iface,
                        "vendor": vendor_name,
                        "vendor_icon": vendor_icon,
                        "rx_speed": format_speed(rx_speed_bps),
                        "tx_speed": format_speed(tx_speed_bps),
                        "rx_speed_bps": int(rx_speed_bps),
                        "tx_speed_bps": int(tx_speed_bps),
                        "total_rx": format_bytes(cur_rx_b) if cur_rx_b > 0 else "-",
                        "total_tx": format_bytes(cur_tx_b) if cur_tx_b > 0 else "-",
                        "link_rate": cur_rate
                    })
            except Exception:
                pass

            # 2b. Query iwinfo assoclist (FALLBACK: for Broadcom or missing iw dev)
            try:
                assoc = subprocess.check_output(f"iwinfo {iface} assoclist", shell=True, text=True)
                for line in assoc.splitlines():
                    if ' dBm' in line or 'SNR' in line or 'Signal:' in line:
                        parts = line.split()
                        if not parts: continue
                        mac = parts[0].upper()
                        if mac in seen_macs or len(mac) != 17 or mac.count(':') != 5: continue
                        seen_macs.add(mac)
                        sig = -70
                        for p in parts:
                            if p.startswith('-') and p.endswith('dBm'):
                                try: sig = int(p.replace('dBm', ''))
                                except: pass
                        
                        oui = mac[:8]
                        vendor_name, vendor_icon = OUI_MAP.get(oui, ("جهاز غير معروف", "📱"))
                        if len(mac) >= 2 and mac[1].upper() in ['2', '6', 'A', 'E']:
                            vendor_name, vendor_icon = ("ماك عشوائي (Private MAC)", "🔒")

                        clients.append({
                            "mac": mac,
                            "signal": sig,
                            "iface": iface,
                            "vendor": vendor_name,
                            "vendor_icon": vendor_icon,
                            "rx_speed": "-",
                            "tx_speed": "-",
                            "rx_speed_bps": 0,
                            "tx_speed_bps": 0,
                            "total_rx": "-",
                            "total_tx": "-",
                            "link_rate": "-"
                        })
            except Exception:
                pass

    except Exception:
        pass

    PREV_CLIENT_STATS = {m: v for m, v in PREV_CLIENT_STATS.items() if m in seen_macs}
    return clients

def get_radio_temps():
    temps = {}
    import glob, os
    try:
        for z in glob.glob("/sys/class/thermal/thermal_zone*"):
            try:
                z_type = ""
                type_f = os.path.join(z, "type")
                if os.path.exists(type_f):
                    with open(type_f, "r") as tf:
                        z_type = tf.read().strip().lower()
                temp_f = os.path.join(z, "temp")
                if os.path.exists(temp_f):
                    with open(temp_f, "r") as valf:
                        raw_t = int(valf.read().strip())
                        if raw_t > 1000: raw_t = raw_t // 1000
                        if raw_t > 0:
                            t_str = f"{raw_t}°C"
                            if "wifi" in z_type or "wlan" in z_type or "radio" in z_type:
                                temps[z_type] = t_str
                            elif "zone1" in z:
                                temps["radio0"] = t_str
                                temps["2g"] = t_str
                            elif "zone2" in z:
                                temps["radio1"] = t_str
                                temps["5g"] = t_str
                            elif "zone0" in z:
                                temps["cpu"] = t_str
            except Exception:
                pass
    except Exception:
        pass

    try:
        for hw_path in glob.glob("/sys/class/net/*/device/hwmon/hwmon*/temp1_input"):
            try:
                iface = hw_path.split("/sys/class/net/")[1].split("/")[0]
                with open(hw_path, "r") as hf:
                    raw_t = int(hf.read().strip())
                    if raw_t > 1000: raw_t = raw_t // 1000
                    if raw_t > 0:
                        temps[iface] = f"{raw_t}°C"
            except Exception:
                pass
    except Exception:
        pass

    try:
        for hw_dir in glob.glob("/sys/class/hwmon/hwmon*"):
            name_file = os.path.join(hw_dir, "name")
            name = ""
            if os.path.exists(name_file):
                with open(name_file, "r") as nf:
                    name = nf.read().strip().lower()
            for tf in glob.glob(os.path.join(hw_dir, "temp*_input")):
                try:
                    with open(tf, "r") as vf:
                        raw_t = int(vf.read().strip())
                        if raw_t > 1000: raw_t = raw_t // 1000
                        if raw_t > 0:
                            if "ath10k" in name or "qca" in name or "mt76" in name:
                                temps[name] = f"{raw_t}°C"
                except Exception:
                    pass
    except Exception:
        pass

    return temps

def get_wifi_info():
    info = []
    try:
        r_temps = get_radio_temps()
        out = subprocess.check_output("uci show wireless", shell=True, text=True)
        devices = {}
        ifaces = {}
        for line in out.splitlines():
            line = line.strip()
            if not line or '=' not in line: continue
            k, v = line.split('=', 1)
            v = v.strip("'")
            parts = k.split('.')
            if len(parts) >= 3:
                sec = parts[1]
                prop = parts[2]
                if prop == 'type' and v == 'mac80211':
                    devices[sec] = devices.get(sec, {})
                if prop == 'device':
                    ifaces[sec] = ifaces.get(sec, {})
                    ifaces[sec]['device'] = v
                if sec in devices: devices[sec][prop] = v
                elif sec in ifaces: ifaces[sec][prop] = v
                else:
                    if 'radio' in sec:
                        devices[sec] = devices.get(sec, {})
                        devices[sec][prop] = v
                    else:
                        ifaces[sec] = ifaces.get(sec, {})
                        ifaces[sec][prop] = v
        
        iw_data = {}
        try:
            iw_out = subprocess.check_output("iwinfo", shell=True, text=True)
            cur_iface = None
            for line in iw_out.splitlines():
                if line and not line.startswith(' '):
                    cur_iface = line.split()[0]
                    iw_data[cur_iface] = {'iface': cur_iface, 'channels': []}
                    try:
                        f_out = subprocess.check_output(f"iwinfo {cur_iface} freqlist", shell=True, text=True)
                        for f_line in f_out.splitlines():
                            import re
                            m = re.search(r'\(Channel\s+(\d+)\)', f_line) or re.search(r'\[(\d+)\]', f_line)
                            if m:
                                iw_data[cur_iface]['channels'].append(m.group(1))
                    except:
                        pass
                elif cur_iface and line:
                    if 'ESSID:' in line:
                        m = re.search(r'ESSID:\s*"(.*?)"', line)
                        if m: iw_data[cur_iface]['ssid'] = m.group(1)
                    if 'Channel:' in line:
                        m = re.search(r'Channel:\s*(\d+)\s*\((.*?)\)', line)
                        if m:
                            iw_data[cur_iface]['channel'] = int(m.group(1))
                            iw_data[cur_iface]['freq'] = m.group(2)
                    if 'HT Mode:' in line:
                        m = re.search(r'HT Mode:\s*(\S+)', line)
                        if m: iw_data[cur_iface]['htmode'] = m.group(1)
                    if 'Tx-Power:' in line:
                        m = re.search(r'Tx-Power:\s*(\d+)\s*dBm', line)
                        if m: iw_data[cur_iface]['txpower'] = int(m.group(1))
                    if 'Noise:' in line:
                        m = re.search(r'Noise:\s*(-?\d+)\s*dBm', line)
                        if m: iw_data[cur_iface]['noise'] = m.group(1) + ' dBm'
                    if 'Mode:' in line:
                        m = re.search(r'Mode:\s*(\S+)', line)
                        if m: iw_data[cur_iface]['mode'] = m.group(1)
                    if 'Encryption:' in line:
                        m = re.search(r'Encryption:\s*(.*)', line)
                        if m: iw_data[cur_iface]['encryption'] = m.group(1).strip()
        except Exception:
            pass

        # Loop over each configured wireless interface
        for if_name, if_data in ifaces.items():
            dev_name = if_data.get('device', 'radio0')
            dev = devices.get(dev_name, {})
            
            band = dev.get('band', '')
            ch_val = str(dev.get('channel', '')).strip()
            ht_val = str(dev.get('htmode', '')).upper()
            hw_val = str(dev.get('hwmode', '')).lower()

            if not band:
                if ch_val.isdigit() and int(ch_val) >= 36:
                    band = '5g'
                elif 'VHT' in ht_val or 'HE80' in ht_val or 'HE160' in ht_val:
                    band = '5g'
                elif '11a' in hw_val or '11ac' in hw_val or '11ax' in hw_val:
                    band = '5g'
                elif '5' in dev_name or '1' in dev_name:
                    band = '5g'
                else:
                    band = '2g'
            
            ch = dev.get('channel', 'auto')
            htmode = dev.get('htmode', 'HT20')
            txpower = dev.get('txpower', '20')
            disabled = (if_data.get('disabled', '0') == '1') or (dev.get('disabled', '0') == '1')
            ssid = if_data.get('ssid', '')
            enc = if_data.get('encryption', 'none')
            mode = if_data.get('mode', 'ap')
            
            # Match live iwinfo details if available
            supported_channels = []
            noise = "-87 dBm"
            live_enc = enc
            for iw_k, iw_v in iw_data.items():
                if ssid and iw_v.get('ssid') == ssid:
                    if iw_v.get('channel'): ch = str(iw_v['channel'])
                    if iw_v.get('htmode'): htmode = iw_v['htmode']
                    if iw_v.get('txpower'): txpower = str(iw_v['txpower'])
                    if iw_v.get('channels'): supported_channels = iw_v['channels']
                    if iw_v.get('noise'): noise = iw_v['noise']
                    if iw_v.get('encryption'): live_enc = iw_v['encryption']
                    break
            
            if ssid:
                key = if_data.get('key', '')
                b_code = '2g' if band in ['2g', '2.4g', '2.4GHz'] else '5g'
                r_temp = r_temps.get(dev_name) or r_temps.get(b_code) or r_temps.get(if_name) or r_temps.get('cpu') or '-'
                info.append({
                    'device': dev_name,
                    'password': key,
                    'iface_section': if_name,
                    'band': '2.4GHz' if band in ['2g', '2.4g', '2.4GHz'] else '5GHz',
                    'band_code': b_code,
                    'ssid': ssid,
                    'channel': str(ch),
                    'channels': supported_channels,
                    'htmode': htmode,
                    'txpower': str(txpower),
                    'disabled': disabled,
                    'encryption': live_enc,
                    'uci_encryption': enc,
                    'noise': noise,
                    'mode': mode,
                    'temp': r_temp
                })
    except Exception:
        pass
    return info

def apply_wifi_config(action="apply_profile", iface_name="ALL", value="", **kwargs):
    try:
        if "action" in kwargs:
            action = kwargs.pop("action")
        if "iface" in kwargs:
            iface_name = kwargs.pop("iface")
        if "value" in kwargs:
            value = kwargs.pop("value")

        out = subprocess.check_output("uci show wireless", shell=True, text=True)
        lines = out.splitlines()

        if action == "apply_profile":
            target_band = kwargs.get("band", "both")
            ssid = kwargs.get("ssid", "")
            key = kwargs.get("password", "")
            enc = kwargs.get("encryption", "")
            if key and not enc:
                enc = "psk2"
            channel = kwargs.get("channel", "")
            htmode = kwargs.get("htmode", "")

            devices = {}
            ifaces = {}
            for line in lines:
                if "=" not in line: continue
                k, v = line.split("=", 1)
                v = v.strip("'")
                parts = k.split(".")
                if len(parts) == 2 and v == "wifi-device":
                    devices[parts[1]] = {"id": parts[1]}
                elif len(parts) == 2 and v == "wifi-iface":
                    ifaces[parts[1]] = {"id": parts[1]}
                elif len(parts) == 3:
                    sec = parts[1]
                    prop = parts[2]
                    if sec in devices: devices[sec][prop] = v
                    if sec in ifaces: ifaces[sec][prop] = v
            
            target_dev = kwargs.get("device", "")
            changed = False
            for dev_id, ddata in devices.items():
                d_band = ddata.get("band", "")
                d_hwmode = ddata.get("hwmode", "")
                
                is_2g = (d_band == "2g" or d_hwmode in ["11b", "11g"])
                is_5g = (d_band in ["5g", "6g"] or d_hwmode in ["11a", "11ac", "11ax"])
                
                if not is_2g and not is_5g:
                    if "5" in dev_id or "1" in dev_id: is_5g = True
                    else: is_2g = True

                match = False
                if target_dev and target_dev == dev_id: match = True
                elif target_band == "both": match = True
                elif target_band == "2g" and is_2g: match = True
                elif target_band == "5g" and is_5g: match = True

                if match:
                    if channel:
                        cur_ch = ddata.get("channel", "")
                        if channel == "auto" or channel == "0":
                            if cur_ch != "auto" and cur_ch != "0":
                                subprocess.run(["uci", "set", f"wireless.{dev_id}.channel=auto"])
                                changed = True
                        elif str(channel) != str(cur_ch):
                            subprocess.run(["uci", "set", f"wireless.{dev_id}.channel={channel}"])
                            changed = True
                    if htmode:
                        cur_ht = ddata.get("htmode", "")
                        if str(htmode) != str(cur_ht):
                            subprocess.run(["uci", "set", f"wireless.{dev_id}.htmode={htmode}"])
                            changed = True

            # Apply interface level settings (ssid, key, enc)
            for iface_id, idata in ifaces.items():
                dev = idata.get("device")
                if not dev or dev not in devices: continue

                ddata = devices[dev]
                d_band = ddata.get("band", "")
                d_hwmode = ddata.get("hwmode", "")
                
                is_2g = (d_band == "2g" or d_hwmode in ["11b", "11g"])
                is_5g = (d_band in ["5g", "6g"] or d_hwmode in ["11a", "11ac", "11ax"])
                
                if not is_2g and not is_5g:
                    if "5" in dev or "1" in dev: is_5g = True
                    else: is_2g = True

                match = False
                if target_dev and target_dev == dev: match = True
                elif target_band == "both": match = True
                elif target_band == "2g" and is_2g: match = True
                elif target_band == "5g" and is_5g: match = True

                if match:
                    if ssid:
                        cur_ssid = idata.get("ssid", "")
                        if str(ssid) != str(cur_ssid):
                            subprocess.run(["uci", "set", f"wireless.{iface_id}.ssid={ssid}"])
                            changed = True
                    
                    if enc is not None and enc != "":
                        enc_val = enc.lower().strip()
                        cur_enc = idata.get("encryption", "")
                        if enc_val in ["none", "open"]:
                            if cur_enc != "none":
                                subprocess.run(["uci", "set", f"wireless.{iface_id}.encryption=none"])
                                subprocess.run(["uci", "-q", "delete", f"wireless.{iface_id}.key"])
                                subprocess.run(["uci", "-q", "delete", f"wireless.{iface_id}.ieee80211w"])
                                changed = True
                        else:
                            if enc_val in ["psk2", "wpa2", "psk2+ccmp"]:
                                uci_enc = "psk2"
                            elif enc_val in ["psk-mixed", "mixed-psk", "wpa-mixed"]:
                                uci_enc = "psk-mixed"
                            elif enc_val in ["sae", "wpa3"]:
                                uci_enc = "sae"
                                subprocess.run(["uci", "set", f"wireless.{iface_id}.ieee80211w=2"])
                            elif enc_val in ["sae-mixed", "wpa3-mixed", "wpa2/wpa3"]:
                                uci_enc = "sae-mixed"
                                subprocess.run(["uci", "set", f"wireless.{iface_id}.ieee80211w=1"])
                            else:
                                uci_enc = enc_val
                            
                            if uci_enc != cur_enc:
                                subprocess.run(["uci", "set", f"wireless.{iface_id}.encryption={uci_enc}"])
                                changed = True
                            if key and 8 <= len(key) <= 63:
                                cur_key = idata.get("key", "")
                                if key != cur_key:
                                    subprocess.run(["uci", "set", f"wireless.{iface_id}.key={key}"])
                                    changed = True
                    elif key and 8 <= len(key) <= 63:
                        cur_key = idata.get("key", "")
                        if key != cur_key:
                            subprocess.run(["uci", "set", f"wireless.{iface_id}.key={key}"])
                            subprocess.run(["uci", "set", f"wireless.{iface_id}.encryption=psk2"])
                            changed = True
            
            if changed:
                subprocess.run(["uci", "commit", "wireless"])
                request_wifi_reload()
            return
                    
        if action == "radio_restart":
            radio_target = kwargs.get("radio") or iface_name or "radio0"
            request_wifi_reload(radio_target)
            return

        if action == "radio_state":
            radio_target = kwargs.get("radio") or iface_name or "radio0"
            state_val = kwargs.get("state") or value
            n_state = "1" if state_val == "disable" else "0"
            subprocess.run(["uci", "set", f"wireless.{radio_target}.disabled={n_state}"])
            subprocess.run(["uci", "commit", "wireless"])
            request_wifi_reload(radio_target)
            return

        # Legacy logic for single interface actions
        section = None
        for line in lines:
            if iface_name == "ALL" and ".device=" not in line and "wifi-iface" in line:
                section = line.split('.')[1]
                break
            if f"ifname='{iface_name}'" in line or f"ifname={iface_name}" in line or f"device='{iface_name}'" in line:
                section = line.split('.')[1]
                break
        
        if section:
            if action == "set_password":
                subprocess.run(["uci", "set", f"wireless.{section}.key={value}"])
                subprocess.run(["uci", "set", f"wireless.{section}.encryption=psk2"])
            elif action == "set_ssid":
                subprocess.run(["uci", "set", f"wireless.{section}.ssid={value}"])
            elif action == "set_channel":
                try:
                    dev_out = subprocess.check_output(["uci", "-q", "get", f"wireless.{section}.device"], text=True).strip() or section
                except Exception:
                    dev_out = section
                subprocess.run(["uci", "set", f"wireless.{dev_out}.channel={value}"])
            elif action == "set_mode":
                subprocess.run(["uci", "set", f"wireless.{section}.mode={value}"])
            elif action == "set_encryption":
                subprocess.run(["uci", "set", f"wireless.{section}.encryption={value}"])
            elif action == "set_htmode":
                try:
                    dev_out = subprocess.check_output(["uci", "-q", "get", f"wireless.{section}.device"], text=True).strip() or section
                except Exception:
                    dev_out = section
                subprocess.run(["uci", "set", f"wireless.{dev_out}.htmode={value}"])
            
            subprocess.run(["uci", "commit", "wireless"])
            request_wifi_reload()
    except Exception:
        log.exception("apply_wifi_config failed")

def steer_client_locally(mac, target_bssid=None, ban_time=3000):
    try:
        out = subprocess.check_output("ubus list | grep hostapd", shell=True, text=True)
        for h in out.splitlines():
            h = h.strip()
            if not h or not h.startswith("hostapd."): continue
            # 1. 802.11v BSS Transition Request
            if target_bssid:
                try:
                    subprocess.run(
                        f"ubus call {h} bss_transition_request '{{\"addr\":\"{mac}\", \"disassociation_imminent\":true, \"disassociation_timer\":10, \"neighbors\":[\"{target_bssid}\"]}}'",
                        shell=True, timeout=2
                    )
                except Exception:
                    pass
            # 2. Deauthenticate / Disassociate with probe suppression ban_time (forces association to closer AP)
            try:
                subprocess.run(
                    f"ubus call {h} del_client '{{\"addr\":\"{mac}\", \"reason\":1, \"deauth\":true, \"ban_time\":{ban_time}}}'",
                    shell=True, timeout=2
                )
            except Exception:
                pass
    except Exception:
        log.debug("steer_client_locally failed", exc_info=True)

def enable_80211kv_locally():
    try:
        out = subprocess.check_output("uci show wireless", shell=True, text=True)
        ifaces = [l.split('.')[1].split('=')[0] for l in out.splitlines() if 'wifi-iface' in l and '=wifi-iface' in l]
        for iface in ifaces:
            subprocess.run(["uci", "set", f"wireless.{iface}.ieee80211k=1"])
            subprocess.run(["uci", "set", f"wireless.{iface}.ieee80211v=1"])
            subprocess.run(["uci", "set", f"wireless.{iface}.bss_transition=1"])
            subprocess.run(["uci", "set", f"wireless.{iface}.wnm_sleep_mode=1"])
        subprocess.run(["uci", "commit", "wireless"])
        request_wifi_reload()
    except Exception:
        log.exception("enable_80211kv_locally failed")



def get_scan_data():
    scan_results = {}
    try:
        # Auto-detect first wireless interface instead of hardcoding wlan0
        scan_iface = "wlan0"
        try:
            net_devs = os.listdir("/sys/class/net")
            for dev in net_devs:
                if os.path.exists(f"/sys/class/net/{dev}/phy80211") or os.path.exists(f"/sys/class/net/{dev}/wireless"):
                    scan_iface = dev
                    break
        except Exception:
            pass
        out = subprocess.check_output(f"iwinfo {scan_iface} scan 2>/dev/null || iw dev {scan_iface} scan 2>/dev/null", shell=True, text=True)
        for line in out.splitlines():
            if "Channel:" in line or "channel" in line:
                for part in line.split():
                    if part.isdigit():
                        scan_results[part] = scan_results.get(part, 0) + 1
    except Exception:
        pass
    return scan_results

def get_wifi_radios_and_macs():
    res = {"5g": [], "2g": [], "all": []}
    try:
        net_devs = os.listdir("/sys/class/net")
        for dev in net_devs:
            phy_path = f"/sys/class/net/{dev}/phy80211"
            w_path = f"/sys/class/net/{dev}/wireless"
            if os.path.exists(phy_path) or os.path.exists(w_path) or any(dev.startswith(p) for p in ["wlan", "phy", "ath", "ra", "wl"]):
                try:
                    with open(f"/sys/class/net/{dev}/address", "r") as f:
                        mac = f.read().strip().upper()
                    if mac and len(mac) == 17 and mac != "00:00:00:00:00:00":
                        if mac not in res["all"]:
                            res["all"].append(mac)
                        
                        is_5g = False
                        try:
                            iw_out = subprocess.check_output(f"iwinfo {dev} info 2>/dev/null", shell=True, text=True)
                            ch_m = re.search(r'Channel:\s*(\d+)', iw_out)
                            if ch_m and int(ch_m.group(1)) >= 36:
                                is_5g = True
                            elif re.search(r'\(5\.\d+\s*GHz\)', iw_out) or any(k in iw_out for k in ["5 GHz", "5GHz", "802.11a", "802.11an", "802.11ac", "802.11ax"]):
                                is_5g = True
                            elif "2.4" in iw_out or "2 GHz" in iw_out or (ch_m and int(ch_m.group(1)) <= 14):
                                is_5g = False
                        except Exception:
                            pass

                        if not is_5g:
                            try:
                                d_out = subprocess.check_output(f"iw dev {dev} info 2>/dev/null", shell=True, text=True)
                                ch_m = re.search(r'channel\s*(\d+)', d_out)
                                if ch_m and int(ch_m.group(1)) >= 36:
                                    is_5g = True
                                elif re.search(r'\(5\d{3}\s*MHz\)', d_out):
                                    is_5g = True
                            except Exception:
                                pass

                        if not is_5g and ("1" in dev or "5g" in dev.lower()):
                            is_5g = True
                        
                        if is_5g:
                            if mac not in res["5g"]: res["5g"].append(mac)
                        else:
                            if mac not in res["2g"]: res["2g"].append(mac)
                except Exception:
                    pass
    except Exception:
        pass
    return res

def get_5g_channel_health():
    res = {
        "has_5g": False,
        "iface": "",
        "mode": "ap",
        "bssid": "",
        "connected_bssid": "",
        "channel": 36,
        "htmode": "VHT80",
        "noise": -90,
        "signal": -60,
        "supported_channels": [36, 40, 44, 48, 149, 153, 157, 161],
        "scan_counts": {}
    }

    candidates = []
    try:
        for dev in os.listdir("/sys/class/net"):
            if os.path.exists(f"/sys/class/net/{dev}/phy80211") or os.path.exists(f"/sys/class/net/{dev}/wireless") or any(dev.startswith(p) for p in ["wlan", "phy", "ath", "ra", "wl"]):
                if dev not in candidates and dev != "lo":
                    candidates.append(dev)
    except Exception:
        pass

    try:
        iw_d = subprocess.check_output("iw dev 2>/dev/null", shell=True, text=True)
        for line in iw_d.splitlines():
            line = line.strip()
            if line.startswith("Interface "):
                if_name = line.split()[1]
                if if_name not in candidates:
                    candidates.append(if_name)
    except Exception:
        pass

    for dev in candidates:
        txt = ""
        try:
            txt = subprocess.check_output(f"iwinfo {dev} info 2>/dev/null", shell=True, text=True)
        except Exception:
            txt = ""

        dev_info = ""
        try:
            dev_info = subprocess.check_output(f"iw dev {dev} info 2>/dev/null", shell=True, text=True)
        except Exception:
            dev_info = ""

        is_5g = False
        ch = 0

        # Check channel and frequency from iwinfo
        if txt:
            ch_m = re.search(r'Channel:\s*(\d+)', txt)
            if ch_m:
                ch = int(ch_m.group(1))
            if ch >= 36:
                is_5g = True
            elif re.search(r'\(5\.\d+\s*GHz\)', txt) or any(k in txt for k in ["5 GHz", "5GHz", "802.11a", "802.11an", "802.11ac", "802.11ax"]):
                is_5g = True

        # Fallback to iw dev info
        if not is_5g and dev_info:
            ch_m = re.search(r'channel\s*(\d+)', dev_info)
            if ch_m:
                ch = int(ch_m.group(1))
                if ch >= 36:
                    is_5g = True
            freq_m = re.search(r'\((\d+)\s*MHz\)', dev_info)
            if freq_m and int(freq_m.group(1)) >= 5000:
                is_5g = True

        if is_5g:
            res["has_5g"] = True
            res["iface"] = dev
            if ch:
                res["channel"] = ch

            # Mode detection: STA vs AP
            if "Mode: Client" in txt or "Mode: Station" in txt or "type managed" in dev_info or "sta" in dev:
                res["mode"] = "sta"
            else:
                res["mode"] = "ap"

            if res["mode"] == "sta":
                try:
                    l_out = subprocess.check_output(f"iw dev {dev} link 2>/dev/null", shell=True, text=True)
                    m_l = re.search(r"Connected to\s+([0-9A-Fa-f:]{17})", l_out, re.IGNORECASE)
                    if m_l:
                        res["connected_bssid"] = m_l.group(1).upper()
                    m_l_sig = re.search(r"signal:\s*(-?\d+)", l_out)
                    if m_l_sig:
                        res["signal"] = int(m_l_sig.group(1))
                except Exception:
                    pass
            else:
                m_bssid = re.search(r"Access Point:\s*([0-9A-Fa-f:]{17})", txt) or re.search(r"addr\s+([0-9A-Fa-f:]{17})", dev_info)
                if m_bssid:
                    res["bssid"] = m_bssid.group(1).upper()

            m_noise = re.search(r"Noise:\s*(-?\d+)\s*dBm", txt)
            if m_noise:
                res["noise"] = int(m_noise.group(1))
            m_sig = re.search(r"Signal:\s*(-?\d+)\s*dBm", txt)
            if m_sig:
                res["signal"] = int(m_sig.group(1))

            m_ht = re.search(r"HT Mode:\s*(\S+)", txt)
            if m_ht:
                res["htmode"] = m_ht.group(1)
            elif "width: 160" in dev_info:
                res["htmode"] = "VHT160"
            elif "width: 80" in dev_info:
                res["htmode"] = "VHT80"
            elif "width: 40" in dev_info:
                res["htmode"] = "HT40"
            elif "width: 20" in dev_info:
                res["htmode"] = "HT20"

            try:
                f_out = subprocess.check_output(f"iwinfo {dev} freqlist 2>/dev/null", shell=True, text=True)
                chans = []
                for fl in f_out.splitlines():
                    m = re.search(r"\(Channel\s+(\d+)\)", fl) or re.search(r"\[(\d+)\]", fl)
                    if m:
                        c_num = int(m.group(1))
                        if c_num in [36, 40, 44, 48, 52, 56, 60, 64, 100, 104, 108, 112, 116, 120, 124, 128, 132, 136, 140, 144, 149, 153, 157, 161, 165]:
                            chans.append(c_num)
                if chans:
                    res["supported_channels"] = sorted(list(set(chans)))
            except Exception:
                pass
            break

    # UCI Fallback: If radio is starting or in DFS radar scan
    if not res["has_5g"]:
        try:
            u_out = subprocess.check_output("uci show wireless 2>/dev/null", shell=True, text=True)
            for line in u_out.splitlines():
                if ".band='5g'" in line or ".band='5G'" in line or ".hwmode='11a'" in line or ".hwmode='11ac'" in line or ".hwmode='11ax'" in line or ".htmode='VHT" in line or ".htmode='HE" in line:
                    res["has_5g"] = True
                    break
                if ".channel=" in line:
                    m_c = re.search(r"\.channel='?(\d+)'?", line)
                    if m_c and int(m_c.group(1)) >= 36:
                        res["has_5g"] = True
                        res["channel"] = int(m_c.group(1))
                        break
        except Exception:
            pass

    return res


