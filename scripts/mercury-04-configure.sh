#!/bin/bash
# ===============================================================
# Script 4: Configure OpenWrt for Mercury KM15-103H
# ===============================================================
set -e

cd openwrt

echo "Injecting custom overlay files from mercury_km15_103h_build/files..."
mkdir -p files
cp -r ../mercury_km15_103h_build/files/* files/

echo "Writing target .config for Mercury KM15-103H..."
cat << 'EOF' > .config
# Target System
CONFIG_TARGET_ramips=y
CONFIG_TARGET_ramips_mt7621=y
CONFIG_TARGET_ramips_mt7621_DEVICE_mercury_km15-103h=y

# Wireless Drivers & Firmware
CONFIG_PACKAGE_kmod-mt7915e=y
CONFIG_PACKAGE_mt7915-firmware=y
CONFIG_PACKAGE_kmod-mt76=y
CONFIG_PACKAGE_kmod-mt76-connac=y
CONFIG_PACKAGE_kmod-mt76-core=y
CONFIG_PACKAGE_wireless-regdb=y

# Web Interface & Management
CONFIG_PACKAGE_luci=y
CONFIG_PACKAGE_luci-ssl=y
CONFIG_PACKAGE_luci-app-commands=y
CONFIG_PACKAGE_luci-theme-bootstrap=y
CONFIG_PACKAGE_iwinfo=y
CONFIG_PACKAGE_rpcd=y
CONFIG_PACKAGE_rpcd-mod-luci=y

# System Tools & Utilities
CONFIG_PACKAGE_uboot-envtools=y
CONFIG_PACKAGE_htop=y
CONFIG_PACKAGE_nano=y
CONFIG_PACKAGE_bash=y
CONFIG_PACKAGE_curl=y
CONFIG_PACKAGE_wget-ssl=y
CONFIG_PACKAGE_ca-bundle=y
CONFIG_PACKAGE_mtd=y
CONFIG_PACKAGE_ubi-utils=y

# Base filesystem
CONFIG_TARGET_ROOTFS_SQUASHFS=y
CONFIG_TARGET_ROOTFS_UBIFS=y
CONFIG_TARGET_UBIFS_COMPRESSION_ZSTD=y

EOF

echo "Running make defconfig..."
make defconfig

echo "Verifying mercury_km15-103h device symbol was actually enabled..."
if ! grep -q '^CONFIG_TARGET_ramips_mt7621_DEVICE_mercury_km15-103h=y' .config; then
	echo "❌ ERROR: CONFIG_TARGET_ramips_mt7621_DEVICE_mercury_km15-103h=y is NOT set in .config after defconfig!"
	echo "This means the device symbol was dropped/rejected by Kconfig - compiling now would silently build"
	echo "the wrong (default) device instead, as happened before. Aborting early instead of wasting a full build."
	echo ""
	echo "--- Any mercury/km15 related lines in .config ---"
	grep -i 'mercury\|km15' .config || echo "(none found - device symbol does not exist at all)"
	echo ""
	echo "--- Does the device block exist in mt7621.mk? ---"
	grep -n -A3 'Device/mercury_km15-103h' target/linux/ramips/image/mt7621.mk || echo "(NOT FOUND in mt7621.mk!)"
	echo ""
	echo "--- Does the DTS file exist? ---"
	ls -la target/linux/ramips/dts/mt7621_mercury_km15-103h.dts 2>&1
	echo ""
	echo "--- Does the Device/dsa-migration macro our block depends on still exist in this OpenWrt version? ---"
	grep -n 'define Device/dsa-migration' target/linux/ramips/image/mt7621.mk || echo "(NOT FOUND - macro may have been renamed/removed upstream)"
	echo ""
	echo "--- First 30 ramips/mt7621 device symbols known to Kconfig (for comparison) ---"
	grep 'CONFIG_TARGET_ramips_mt7621_DEVICE_' .config | head -30
	exit 1
fi
echo "✅ Device symbol confirmed enabled."

echo "✅ Configuration complete."
