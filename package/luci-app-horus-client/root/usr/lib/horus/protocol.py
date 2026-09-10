# -*- coding: utf-8 -*-
import time
import json
import zlib
import socket
import struct
import hmac
import hashlib
import os
import re
import subprocess
import sys
from .config import ETH_P_HMP, UDP_PORT, INTERFACE
from .system import get_my_mac

def compute_hmac(payload_str, secret):
    return hmac.new(secret.encode('utf-8'), payload_str.encode('utf-8'), hashlib.sha256).hexdigest()

def verify_hmac(data_dict, secret):
    if not secret:
        return True
    if 'hmac' not in data_dict:
        return False
    received_hmac = data_dict['hmac']
    data_copy = data_dict.copy()
    del data_copy['hmac']
    if 'sig' in data_copy: del data_copy['sig']
    payload_str = json.dumps(data_copy, sort_keys=True, separators=(',', ':'))
    computed = compute_hmac(payload_str, secret)
    return hmac.compare_digest(received_hmac, computed)

def mac_str_to_bytes(mac):
    return bytes.fromhex(mac.replace(':', ''))

def get_broadcast_interfaces():
    """Discover all active network interfaces capable of Layer 2 transmission."""
    candidates = []
    try:
        net_dir = '/sys/class/net'
        if os.path.exists(net_dir):
            for dev in os.listdir(net_dir):
                if dev == 'lo' or dev.startswith(('ifb', 'dummy', 'teql', 'tun', 'tap', 'wg', 'sit', 'ip6')):
                    continue
                dev_path = os.path.join(net_dir, dev)
                try:
                    with open(os.path.join(dev_path, 'operstate'), 'r') as f:
                        state = f.read().strip()
                    if state == 'down':
                        continue
                except Exception:
                    pass
                
                try:
                    with open(os.path.join(dev_path, 'flags'), 'r') as f:
                        flags_str = f.read().strip()
                        flags = int(flags_str, 16) if flags_str.startswith('0x') else int(flags_str)
                        if not (flags & 1):
                            continue
                except Exception:
                    pass
                
                candidates.append(dev)
    except Exception:
        pass
    
    if not candidates:
        return [INTERFACE] if INTERFACE else ['br-lan']
    
    def sort_key(name):
        if name.startswith(('br-', 'br0')): return 0
        if any(name.startswith(p) for p in ['wlan', 'phy', 'ath', 'ra', 'wl']): return 1
        if name.startswith('eth'): return 2
        return 3
    
    candidates.sort(key=sort_key)
    return candidates

def get_subnet_broadcasts():
    """Extract all active IPv4 broadcast addresses from local interfaces."""
    bcasts = set()
    try:
        out = subprocess.check_output("ip -4 -o addr show 2>/dev/null", shell=True, text=True)
        for line in out.splitlines():
            m = re.search(r'brd\s+([0-9.]+)', line)
            if m:
                bcasts.add(m.group(1))
    except Exception:
        pass
    return list(bcasts)

def create_sockets():
    raw_sock = None
    try:
        proto = socket.htons(ETH_P_HMP)
        raw_sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, proto)
        # Note: In Linux AF_PACKET, leaving the socket unbound listens on ALL interfaces
        # (br-lan, wlan0, wlan1, eth0, wwan, etc.) for EtherType ETH_P_HMP (0x88B5).
        raw_sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024 * 1024)
        raw_sock.setblocking(False)
    except Exception as e:
        print(f"L2 Raw Socket info: {e}")

    udp_sock = None
    try:
        udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        udp_sock.bind(("0.0.0.0", UDP_PORT))
        udp_sock.setblocking(False)
    except Exception as e:
        print(f"L3 UDP Socket info: {e}")

    return raw_sock, udp_sock

def send_hmp_frame(raw_sock, udp_sock, payload_dict, dst_mac="FF:FF:FF:FF:FF:FF", dst_ip="", secret=""):
    payload = payload_dict.copy()
    payload['ts'] = int(time.time())
    if 'hmac' in payload:
        del payload['hmac']
    if secret:
        payload_str = json.dumps(payload, sort_keys=True, separators=(',', ':'))
        payload['hmac'] = compute_hmac(payload_str, secret)
    
    encoded_bytes = zlib.compress(json.dumps(payload, separators=(',', ':')).encode('utf-8'))
    
    # 1. Send via Layer 2 Raw Ethernet Socket across all active interfaces
    # Always use FF:FF:FF:FF:FF:FF at the L2 Ethernet header so intermediate bridges,
    # WDS links, and switches flood the frame without dropping unlearned br-lan MACs.
    if raw_sock:
        try:
            dst_bytes = mac_str_to_bytes("FF:FF:FF:FF:FF:FF")
            src_bytes = mac_str_to_bytes(get_my_mac())
            eth_type = struct.pack("!H", ETH_P_HMP)
            frame = dst_bytes + src_bytes + eth_type + encoded_bytes
            
            for iface in get_broadcast_interfaces():
                try:
                    raw_sock.sendto(frame, (iface, ETH_P_HMP))
                except Exception:
                    try:
                        raw_sock.sendto(frame, (iface, 0))
                    except Exception:
                        pass
        except Exception:
            pass

    # 2. Send via Layer 3 UDP Socket (Broadcast & subnet fallback)
    if udp_sock and dst_ip and dst_ip not in ["", "0.0.0.0"]:
        targets = []
        if dst_ip == "255.255.255.255":
            targets.append('<broadcast>')
            for bcast in get_subnet_broadcasts():
                if bcast not in targets:
                    targets.append(bcast)
        elif isinstance(dst_ip, (tuple, list)) and len(dst_ip) >= 2:
            targets.append((str(dst_ip[0]), int(dst_ip[1])))
        else:
            targets.append(str(dst_ip))
            
        for target in targets:
            try:
                if isinstance(target, tuple):
                    udp_sock.sendto(encoded_bytes, target)
                else:
                    udp_sock.sendto(encoded_bytes, (target, UDP_PORT))
            except Exception:
                pass

def parse_incoming_data(raw_data, is_l2=True, secret="", my_mac=""):
    try:
        if is_l2:
            if len(raw_data) < 14: return None
            # Check for 802.1Q VLAN tagging (EtherType 0x8100 at byte 12)
            eth_proto = struct.unpack("!H", raw_data[12:14])[0]
            if eth_proto == 0x8100 and len(raw_data) >= 18:
                payload_bytes = raw_data[18:]
            else:
                payload_bytes = raw_data[14:]
        else:
            payload_bytes = raw_data
        
        try:
            decompressed = zlib.decompress(payload_bytes)
            data = json.loads(decompressed.decode('utf-8').rstrip('\x00'))
        except Exception:
            data = json.loads(payload_bytes.decode('utf-8').rstrip('\x00'))
        
        is_auth = False
        if secret and verify_hmac(data, secret):
            is_auth = True
            
        # Rescue backdoor: allows only set_api_key action & heartbeats (for initial adoption)
        is_rescue = False
        if not is_auth:
            candidate_macs = set()
            if my_mac:
                candidate_macs.add(str(my_mac).upper())
            target_mac = data.get("target_mac") or data.get("target_ap")
            if target_mac and str(target_mac).upper() not in ["ALL", "FF:FF:FF:FF:FF:FF"]:
                candidate_macs.add(str(target_mac).upper())
            src_mac = data.get("src_mac") or data.get("mac")
            if src_mac:
                candidate_macs.add(str(src_mac).upper())
                
            for m in candidate_macs:
                rescue_secret = m + "_horus_rescue"
                if verify_hmac(data, rescue_secret):
                    is_rescue = True
                    break
            
            if is_rescue:
                msg_type = data.get("type", "")
                action = data.get("action", "")
                if msg_type == "ap_manage" and action == "set_api_key":
                    is_auth = True
                elif msg_type in ["root_heartbeat", "root_announce"]:
                    is_auth = True
                
        data['_is_auth'] = is_auth
        data['_is_rescue'] = is_rescue
        return data
    except Exception:
        return None

