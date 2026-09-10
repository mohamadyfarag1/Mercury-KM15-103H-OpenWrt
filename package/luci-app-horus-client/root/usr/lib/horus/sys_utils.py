# -*- coding: utf-8 -*-
import subprocess

def get_uci(path, default=None):
    try:
        out = subprocess.check_output(f"uci -q get {path}", shell=True, text=True).strip()
        return out if out else default
    except Exception:
        return default

def format_speed(bps):
    if bps >= 1000000:
        return f"{bps / 1000000:.1f} Mbps"
    elif bps >= 1000:
        return f"{bps / 1000:.0f} Kbps"
    else:
        return f"{bps:.0f} bps"

def format_bytes(b):
    if b >= 1073741824:
        return f"{b / 1073741824:.2f} GB"
    elif b >= 1048576:
        return f"{b / 1048576:.1f} MB"
    elif b >= 1024:
        return f"{b / 1024:.0f} KB"
    else:
        return f"{b} B"

OUI_MAP = {
    # Apple
    "00:03:93": ("Apple", "🍎"), "00:05:02": ("Apple", "🍎"), "00:0A:27": ("Apple", "🍎"), "00:0A:95": ("Apple", "🍎"),
    "00:0D:93": ("Apple", "🍎"), "00:10:FA": ("Apple", "🍎"), "00:11:24": ("Apple", "🍎"), "00:14:51": ("Apple", "🍎"),
    "00:16:CB": ("Apple", "🍎"), "00:17:F2": ("Apple", "🍎"), "00:19:E3": ("Apple", "🍎"), "00:1B:63": ("Apple", "🍎"),
    "00:1C:B3": ("Apple", "🍎"), "00:1D:4F": ("Apple", "🍎"), "00:1E:52": ("Apple", "🍎"), "00:1E:C2": ("Apple", "🍎"),
    "00:1F:5B": ("Apple", "🍎"), "00:1F:F3": ("Apple", "🍎"), "00:21:E9": ("Apple", "🍎"), "00:22:41": ("Apple", "🍎"),
    "00:23:12": ("Apple", "🍎"), "00:23:32": ("Apple", "🍎"), "00:23:6C": ("Apple", "🍎"), "00:23:DF": ("Apple", "🍎"),
    "00:24:36": ("Apple", "🍎"), "00:25:00": ("Apple", "🍎"), "00:25:4B": ("Apple", "🍎"), "00:25:BC": ("Apple", "🍎"),
    "00:26:08": ("Apple", "🍎"), "00:26:4A": ("Apple", "🍎"), "00:26:B0": ("Apple", "🍎"), "00:26:BB": ("Apple", "🍎"),
    "18:AF:61": ("Apple", "🍎"), "28:CF:E9": ("Apple", "🍎"), "34:36:3B": ("Apple", "🍎"), "38:CA:DA": ("Apple", "🍎"),
    "3C:D0:F8": ("Apple", "🍎"), "40:6C:8F": ("Apple", "🍎"), "44:4C:0C": ("Apple", "🍎"), "48:D7:05": ("Apple", "🍎"),
    "4C:32:75": ("Apple", "🍎"), "50:BC:96": ("Apple", "🍎"), "54:26:96": ("Apple", "🍎"), "58:55:CA": ("Apple", "🍎"),
    "5C:95:AE": ("Apple", "🍎"), "60:03:08": ("Apple", "🍎"), "64:20:0C": ("Apple", "🍎"), "68:96:7B": ("Apple", "🍎"),
    "6C:40:08": ("Apple", "🍎"), "70:11:24": ("Apple", "🍎"), "74:E1:B6": ("Apple", "🍎"), "78:7B:8A": ("Apple", "🍎"),
    "7C:04:D0": ("Apple", "🍎"), "80:49:71": ("Apple", "🍎"), "84:78:8B": ("Apple", "🍎"), "88:66:5A": ("Apple", "🍎"),
    "8C:85:90": ("Apple", "🍎"), "90:72:40": ("Apple", "🍎"), "94:10:3E": ("Apple", "🍎"), "98:01:A7": ("Apple", "🍎"),
    "9C:20:7B": ("Apple", "🍎"), "A0:99:9B": ("Apple", "🍎"), "A4:C3:61": ("Apple", "🍎"), "A8:66:7F": ("Apple", "🍎"),
    "AC:BC:32": ("Apple", "🍎"), "B0:34:95": ("Apple", "🍎"), "B4:18:D1": ("Apple", "🍎"), "B8:78:2E": ("Apple", "🍎"),
    "BC:54:51": ("Apple", "🍎"), "C0:84:7D": ("Apple", "🍎"), "C4:2C:03": ("Apple", "🍎"), "C8:69:CD": ("Apple", "🍎"),
    "CC:25:EF": ("Apple", "🍎"), "D0:23:DB": ("Apple", "🍎"), "D4:90:9C": ("Apple", "🍎"), "D8:96:95": ("Apple", "🍎"),
    "DC:52:85": ("Apple", "🍎"), "E0:B9:BA": ("Apple", "🍎"), "E4:8B:7F": ("Apple", "🍎"), "E8:80:2E": ("Apple", "🍎"),
    "EC:35:86": ("Apple", "🍎"), "F0:18:98": ("Apple", "🍎"), "F4:0F:24": ("Apple", "🍎"), "F8:27:93": ("Apple", "🍎"),
    "FC:FC:48": ("Apple", "🍎"),

    # Samsung
    "00:07:AB": ("Samsung", "📱"), "00:12:47": ("Samsung", "📱"), "00:15:B9": ("Samsung", "📱"), "00:16:32": ("Samsung", "📱"),
    "00:17:D5": ("Samsung", "📱"), "00:1A:8A": ("Samsung", "📱"), "00:1C:43": ("Samsung", "📱"), "00:1E:E2": ("Samsung", "📱"),
    "00:21:19": ("Samsung", "📱"), "00:23:39": ("Samsung", "📱"), "00:26:5D": ("Samsung", "📱"), "08:37:3D": ("Samsung", "📱"),
    "14:49:E0": ("Samsung", "📱"), "18:22:7E": ("Samsung", "📱"), "18:83:BF": ("Samsung", "📱"), "24:4B:81": ("Samsung", "📱"),
    "28:98:7B": ("Samsung", "📱"), "30:07:4D": ("Samsung", "📱"), "34:BE:00": ("Samsung", "📱"), "38:0A:94": ("Samsung", "📱"),
    "40:0E:85": ("Samsung", "📱"), "44:80:EB": ("Samsung", "📱"), "48:44:F7": ("Samsung", "📱"), "4C:66:41": ("Samsung", "📱"),
    "50:01:D9": ("Samsung", "📱"), "54:92:BE": ("Samsung", "📱"), "58:C3:8B": ("Samsung", "📱"), "5C:A3:9D": ("Samsung", "📱"),
    "60:A1:0A": ("Samsung", "📱"), "64:1C:B0": ("Samsung", "📱"), "68:EB:AE": ("Samsung", "📱"), "6C:2F:2C": ("Samsung", "📱"),
    "70:2C:1F": ("Samsung", "📱"), "74:45:8A": ("Samsung", "📱"), "78:1F:DB": ("Samsung", "📱"), "7C:38:AD": ("Samsung", "📱"),
    "80:57:19": ("Samsung", "📱"), "84:25:DB": ("Samsung", "📱"), "88:32:9B": ("Samsung", "📱"), "8C:77:12": ("Samsung", "📱"),
    "90:18:7C": ("Samsung", "📱"), "94:63:72": ("Samsung", "📱"), "98:0D:2E": ("Samsung", "📱"), "9C:02:98": ("Samsung", "📱"),
    "A0:0B:BA": ("Samsung", "📱"), "A4:77:33": ("Samsung", "📱"), "A8:06:00": ("Samsung", "📱"), "AC:5F:3E": ("Samsung", "📱"),
    "B0:47:BF": ("Samsung", "📱"), "B4:52:7D": ("Samsung", "📱"), "B8:5E:7B": ("Samsung", "📱"), "BC:72:B7": ("Samsung", "📱"),
    "C0:97:27": ("Samsung", "📱"), "C4:42:02": ("Samsung", "📱"), "C8:14:79": ("Samsung", "📱"), "CC:07:AB": ("Samsung", "📱"),
    "D0:59:E4": ("Samsung", "📱"), "D4:87:D8": ("Samsung", "📱"), "D8:57:EF": ("Samsung", "📱"), "DC:71:44": ("Samsung", "📱"),
    "E0:42:6D": ("Samsung", "📱"), "E4:58:B8": ("Samsung", "📱"), "E8:50:8B": ("Samsung", "📱"), "EC:1F:72": ("Samsung", "📱"),
    "F0:25:B7": ("Samsung", "📱"), "F4:7B:5E": ("Samsung", "📱"), "F8:04:2E": ("Samsung", "📱"), "FC:A1:3E": ("Samsung", "📱"),

    # Xiaomi / Redmi / Poco
    "00:9E:C8": ("Xiaomi", "📱"), "04:CF:8C": ("Xiaomi", "📱"), "0C:1D:AF": ("Xiaomi", "📱"), "10:2A:B3": ("Xiaomi", "📱"),
    "18:59:36": ("Xiaomi", "📱"), "20:34:FB": ("Xiaomi", "📱"), "28:6C:07": ("Xiaomi", "📱"), "34:80:B3": ("Xiaomi", "📱"),
    "38:A4:ED": ("Xiaomi", "📱"), "3C:BD:3E": ("Xiaomi", "📱"), "40:31:3C": ("Xiaomi", "📱"), "50:64:2B": ("Xiaomi", "📱"),
    "58:44:98": ("Xiaomi", "📱"), "58:6B:14": ("Xiaomi", "📱"), "64:CC:2E": ("Xiaomi", "📱"), "68:DF:DD": ("Xiaomi", "📱"),
    "74:23:44": ("Xiaomi", "📱"), "7C:49:EB": ("Xiaomi", "📱"), "80:AD:16": ("Xiaomi", "📱"), "88:C3:97": ("Xiaomi", "📱"),
    "9C:5F:B0": ("Xiaomi", "📱"), "A4:44:D1": ("Xiaomi", "📱"), "AC:C1:EE": ("Xiaomi", "📱"), "B0:1C:0C": ("Xiaomi", "📱"),
    "C4:0B:D4": ("Xiaomi", "📱"), "D4:97:0B": ("Xiaomi", "📱"), "DC:B7:2E": ("Xiaomi", "📱"), "E4:46:DA": ("Xiaomi", "📱"),
    "F8:A4:5F": ("Xiaomi", "📱"), "FC:64:BA": ("Xiaomi", "📱"),

    # Huawei / Honor
    "00:1E:10": ("Huawei", "📱"), "00:25:68": ("Huawei", "📱"), "00:25:9E": ("Huawei", "📱"), "00:46:4B": ("Huawei", "📱"),
    "00:66:4B": ("Huawei", "📱"), "04:25:C5": ("Huawei", "📱"), "08:19:A6": ("Huawei", "📱"), "10:1B:54": ("Huawei", "📱"),
    "18:D0:C5": ("Huawei", "📱"), "20:08:89": ("Huawei", "📱"), "28:31:52": ("Huawei", "📱"), "34:CD:BE": ("Huawei", "📱"),
    "3C:CD:36": ("Huawei", "📱"), "40:4D:8E": ("Huawei", "📱"), "48:46:FB": ("Huawei", "📱"), "4C:1F:CC": ("Huawei", "📱"),
    "54:89:98": ("Huawei", "📱"), "60:E3:27": ("Huawei", "📱"), "70:72:0C": ("Huawei", "📱"), "78:D7:52": ("Huawei", "📱"),
    "80:B6:86": ("Huawei", "📱"), "88:28:B3": ("Huawei", "📱"), "90:4E:91": ("Huawei", "📱"), "9C:C1:72": ("Huawei", "📱"),
    "A4:93:3F": ("Huawei", "📱"), "B4:15:13": ("Huawei", "📱"), "BC:25:E0": ("Huawei", "📱"), "C4:07:2F": ("Huawei", "📱"),
    "D0:2D:B3": ("Huawei", "📱"), "D8:49:0B": ("Huawei", "📱"), "E0:CC:7A": ("Huawei", "📱"), "E8:CD:2D": ("Huawei", "📱"),
    "F4:C7:14": ("Huawei", "📱"), "FC:48:EF": ("Huawei", "📱"),

    # OPPO / Realme / OnePlus
    "00:1F:3B": ("OPPO", "📱"), "14:7D:DA": ("OPPO", "📱"), "20:57:9E": ("Realme", "📱"), "2C:5B:B8": ("OPPO", "📱"),
    "30:75:12": ("OPPO", "📱"), "38:78:62": ("OPPO", "📱"), "44:04:44": ("Realme", "📱"), "50:33:8B": ("OnePlus", "📱"),
    "64:1B:29": ("OPPO", "📱"), "70:1C:E8": ("OPPO", "📱"), "88:12:4E": ("OnePlus", "📱"), "90:7F:61": ("Realme", "📱"),
    "A4:3B:FA": ("OPPO", "📱"), "BC:8C:CD": ("Realme", "📱"), "CC:0D:EC": ("OnePlus", "📱"), "D4:F5:13": ("OPPO", "📱"),
    "E4:0E:EE": ("OPPO", "📱"), "F4:60:E2": ("Realme", "📱"),

    # Vivo / iQOO
    "00:17:7C": ("Vivo", "📱"), "28:FD:80": ("Vivo", "📱"), "34:85:18": ("Vivo", "📱"), "3C:A6:F6": ("Vivo", "📱"),
    "40:2F:86": ("Vivo", "📱"), "50:04:B8": ("Vivo", "📱"), "64:CC:22": ("Vivo", "📱"), "78:23:27": ("Vivo", "📱"),
    "88:40:3B": ("Vivo", "📱"), "98:CD:AC": ("Vivo", "📱"), "A0:86:C6": ("Vivo", "📱"), "C4:BB:4D": ("Vivo", "📱"),

    # Transsion (Infinix, Tecno, Itel)
    "00:18:2D": ("Tecno", "📱"), "18:87:96": ("Infinix", "📱"), "20:B0:01": ("Tecno", "📱"), "2C:22:8B": ("Infinix", "📱"),
    "48:E2:44": ("Transsion", "📱"), "60:83:34": ("Infinix", "📱"), "70:97:56": ("Tecno", "📱"), "80:EA:07": ("Infinix", "📱"),
    "9C:2E:A1": ("Tecno", "📱"), "B4:CD:27": ("Transsion", "📱"), "D8:20:9E": ("Infinix", "📱"), "EC:94:4B": ("Tecno", "📱"),

    # Apple
    "DC:A2:81": ("Apple", "🍎"), "F4:D6:20": ("Apple", "🍎"),

    # Samsung
    "9C:5F:8B": ("Samsung", "📱"),

    # Xiaomi
    "F8:5E:00": ("Xiaomi", "📱"), "58:68:14": ("Xiaomi", "📱"),

    # Vivo
    "C0:05:08": ("Vivo", "📱"),

    # Ubiquiti
    "00:27:22": ("Ubiquiti", "📶"),
}

