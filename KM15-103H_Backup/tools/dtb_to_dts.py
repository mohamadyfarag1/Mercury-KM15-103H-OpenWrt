import os

base_dir = r"c:\Users\hp\OneDrive\Desktop\New folder (3)\hub\Horus-OpenWrt-Final\KM15-103H_Backup\devicetree\base"

def format_property(name, val):
    if len(val) == 0:
        return f"{name};"
    # Try ascii string list
    # Check if null-terminated string
    if val.endswith(b'\x00'):
        parts = val[:-1].split(b'\x00')
        all_ascii = True
        for p in parts:
            if not p:
                continue
            if not (all(0x20 <= b <= 0x7E for b in p)):
                all_ascii = False
                break
        if all_ascii and len(parts) > 0 and all(len(p) > 0 for p in parts):
            strs = ', '.join(f'"{p.decode("ascii")}"' for p in parts)
            return f"{name} = {strs};"
    
    # Try 32-bit big-endian integers if length is multiple of 4
    if len(val) % 4 == 0 and len(val) <= 32:
        ints = [int.from_bytes(val[i:i+4], 'big') for i in range(0, len(val), 4)]
        # Check if values look reasonable (e.g. addresses, sizes, handles)
        hex_ints = ' '.join(f"0x{x:x}" for x in ints)
        return f"{name} = <{hex_ints}>;"
    
    # Otherwise format as byte array [xx xx xx]
    hex_bytes = ' '.join(f"{b:02x}" for b in val)
    return f"{name} = [{hex_bytes}];"

def dump_node(node_path, indent=0):
    ind = "  " * indent
    node_name = os.path.basename(node_path)
    if node_name == "base":
        node_header = "/ {"
    else:
        node_header = f"{ind}{node_name} {{"
    
    lines = [node_header]
    
    # List properties (files) and children (dirs)
    entries = sorted(os.listdir(node_path))
    files = [e for e in entries if os.path.isfile(os.path.join(node_path, e))]
    dirs = [e for e in entries if os.path.isdir(os.path.join(node_path, e))]
    
    for f in files:
        fpath = os.path.join(node_path, f)
        try:
            with open(fpath, "rb") as prop_file:
                val = prop_file.read()
            lines.append(f"{ind}  {format_property(f, val)}")
        except Exception as e:
            lines.append(f"{ind}  // Error reading {f}: {e}")
            
    for d in dirs:
        dpath = os.path.join(node_path, d)
        sub_lines = dump_node(dpath, indent + 1)
        lines.append(sub_lines)
        
    lines.append(f"{ind}}};")
    return "\n".join(lines)

dts_content = dump_node(base_dir)
out_dts_path = r"c:\Users\hp\OneDrive\Desktop\New folder (3)\hub\Horus-OpenWrt-Final\KM15-103H_Backup\mercury_km15_103h.dts"
with open(out_dts_path, "w", encoding="utf-8") as f:
    f.write("/dts-v1/;\n\n" + dts_content)

print(f"Generated DTS saved to {out_dts_path} ({len(dts_content)} chars)")
