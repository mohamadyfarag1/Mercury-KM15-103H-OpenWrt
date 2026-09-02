import os
import re

factory_path = r"c:\Users\hp\OneDrive\Desktop\New folder (3)\hub\Horus-OpenWrt-Final\KM15-103H_Backup\mtd2_Factory.bin"
bootloader_path = r"c:\Users\hp\OneDrive\Desktop\New folder (3)\hub\Horus-OpenWrt-Final\KM15-103H_Backup\mtd0_Bootloader.bin"

def analyze_file(path, label):
    print(f"\n=================== {label} ({path}) ===================")
    if not os.path.exists(path):
        print("File not found!")
        return
    with open(path, "rb") as f:
        data = f.read()
    
    total = len(data)
    c_ff = data.count(b'\xff')
    c_00 = data.count(b'\x00')
    c_data = total - c_ff - c_00
    print(f"Total size: {total} bytes ({total // 1024} KB)")
    print(f"0xFF bytes: {c_ff} ({c_ff/total*100:.1f}%)")
    print(f"0x00 bytes: {c_00} ({c_00/total*100:.1f}%)")
    print(f"Real data bytes: {c_data} ({c_data/total*100:.1f}%)")
    
    print("\nNon-empty 4KB blocks:")
    for offset in range(0, total, 4096):
        chunk = data[offset:offset+4096]
        if chunk != b'\xff' * 4096 and chunk != b'\x00' * 4096:
            non_ff = 4096 - chunk.count(b'\xff')
            first_16_hex = ' '.join(f"{b:02x}" for b in chunk[:16])
            print(f"  Offset 0x{offset:06X}: {non_ff} bytes non-0xFF | First 16 bytes: {first_16_hex}")
    
    # Search for readable ASCII strings (len >= 4)
    print("\nInteresting ASCII strings found:")
    strings = re.findall(rb'[ -~]{4,}', data)
    for s in strings[:30]:
        try:
            print("  ", s.decode('ascii'))
        except:
            pass

analyze_file(factory_path, "FACTORY / CALDATA (mtd2)")
analyze_file(bootloader_path, "BOOTLOADER (mtd0)")
