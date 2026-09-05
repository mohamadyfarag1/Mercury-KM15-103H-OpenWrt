#!/bin/bash
# ===============================================================
# Script 3: Patch platform.sh and inject dual-boot mercury.sh
# ===============================================================
set -e

cd openwrt

echo "Injecting upgrade scripts..."
mkdir -p package/base-files/files/lib/upgrade
mkdir -p target/linux/ramips/base-files/lib/upgrade
cp ../mercury_km15_103h_build/files/lib/upgrade/mercury.sh package/base-files/files/lib/upgrade/mercury.sh
cp ../mercury_km15_103h_build/files/lib/upgrade/mercury.sh target/linux/ramips/base-files/lib/upgrade/mercury.sh
# Our overlay platform.sh (files/) already takes precedence over the
# target platform.sh at image-build time (mercury-04 copies files/*
# into openwrt/files/ which wins). This explicit copy into the ramips
# base-files as well makes the intent unambiguous and ensures it is
# present even if the overlay copy ever gets missed.
cp ../mercury_km15_103h_build/files/lib/upgrade/platform.sh target/linux/ramips/base-files/lib/upgrade/platform.sh

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
\t\tlocal wan_mac lan_mac
\t\twan_mac=\\$(mtd_get_mac_binary Config 0x4)
\t\tif [ -z "\\$wan_mac" ] || [ "\\$wan_mac" = "00:00:00:00:00:00" ] || [ "\\$wan_mac" = "ff:ff:ff:ff:ff:ff" ]; then
\t\t\twan_mac=\\$(mtd_get_mac_binary Config 0x20004)
\t\tfi
\t\tif [ -z "\\$wan_mac" ] || [ "\\$wan_mac" = "00:00:00:00:00:00" ] || [ "\\$wan_mac" = "ff:ff:ff:ff:ff:ff" ]; then
\t\t\twan_mac=\\$(mtd_get_mac_binary Factory 0x4)
\t\tfi
\t\tif [ -n "\\$wan_mac" ]; then
\t\t\tlan_mac=\\$(macaddr_add "\\$wan_mac" 1)
\t\t\tucidef_set_interface_macaddr "lan" "\\$lan_mac"
\t\t\tucidef_set_interface_macaddr "wan" "\\$wan_mac"
\t\tfi
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
