#!/bin/bash
# ===============================================================
# Script 3: Patch platform.sh and inject dual-boot mercury.sh
# ===============================================================
set -e

cd openwrt

echo "Injecting dual-slot mercury.sh upgrade script..."
mkdir -p package/base-files/files/lib/upgrade
mkdir -p target/linux/ramips/base-files/lib/upgrade
cp ../mercury_km15_103h_build/files/lib/upgrade/mercury.sh package/base-files/files/lib/upgrade/mercury.sh
cp ../mercury_km15_103h_build/files/lib/upgrade/mercury.sh target/linux/ramips/base-files/lib/upgrade/mercury.sh

# Patch target platform.sh for ramips
PLATFORM_SH="target/linux/ramips/base-files/lib/upgrade/platform.sh"
if [ -f "$PLATFORM_SH" ]; then
    if ! grep -q "mercury,km15-103h" "$PLATFORM_SH"; then
        echo "Patching $PLATFORM_SH to hook mercury_do_upgrade..."
        # Add mercury_do_upgrade to platform_do_upgrade case switch
        python3 -c '
import re, sys
path = sys.argv[1]
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

target_block = """\tmercury,km15-103h)
\t\tmercury_do_upgrade "$1"
\t\t;;
"""

if "mercury,km15-103h" not in content:
    # Insert before default_do_upgrade or closing case
    if "default_do_upgrade" in content:
        content = content.replace("default_do_upgrade", target_block + "\tdefault_do_upgrade")
    elif "nand_do_upgrade" in content:
        content = content.replace("nand_do_upgrade \"$1\"", "nand_do_upgrade \"$1\"\n" + target_block)

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print("platform.sh patched successfully.")
' "$PLATFORM_SH"
    fi
fi

# Setup board network & leds in board.d
echo "Setting up board network and leds in target/linux/ramips/base-files/etc/board.d/..."
BOARD_NET="target/linux/ramips/base-files/etc/board.d/02_network"
if [ -f "$BOARD_NET" ]; then
    python3 -c '
import re, sys
path = sys.argv[1]
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

entry = """\tmercury,km15-103h)
\t\tucidef_set_interfaces_lan_wan "lan1 lan2 lan3 lan4" "wan"
\t\t;;
"""
if "mercury,km15-103h" not in content:
    content = re.sub(r"(case\s+\"\$board\"\s+in)", r"\1\n" + entry, content, count=1)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("02_network patched for mercury,km15-103h.")
' "$BOARD_NET"
fi

echo "✅ Platform upgrade scripts setup complete."
