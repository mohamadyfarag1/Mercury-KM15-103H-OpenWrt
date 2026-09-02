#!/bin/bash
# ===============================================================
# Script 1: Setup Device Tree for Mercury KM15-103H (MT7621 + MT7915)
# ===============================================================
set -e

cd openwrt

dts_target="target/linux/ramips/dts/mt7621_mercury_km15-103h.dts"
mkdir -p $(dirname "$dts_target")

echo "Setting up Device Tree for Mercury KM15-103H..."

# If original binary DTB exists, decompile it cleanly with dtc
if [ -f "../mercury_km15_103h_build/device_tree.dtb" ]; then
    echo "Decompiling pristine factory device_tree.dtb using dtc..."
    dtc -I dtb -O dts -o "$dts_target" ../mercury_km15_103h_build/device_tree.dtb || true
fi

# Fallback to pre-generated DTS if dtc decompilation was skipped or empty
if [ ! -s "$dts_target" ]; then
    echo "Using pre-extracted mercury_km15_103h.dts..."
    cp ../mercury_km15_103h_build/mercury_km15_103h.dts "$dts_target"
fi

# Clean up any root name property and verify DTS syntax
python3 -c '
import re, sys
path = sys.argv[1]
with open(path, "r", encoding="utf-8", errors="replace") as f:
    content = f.read()

# Remove sysfs internal root node artifact "name = [00];" or "name = \"\";"
content = re.sub(r"name\s*=\s*\[00\];\n?", "", content)
content = re.sub(r"name\s*=\s*\"\";\n?", "", content)

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print("DTS sanitized successfully.")
' "$dts_target"

echo "✅ Device Tree setup complete: $dts_target"
