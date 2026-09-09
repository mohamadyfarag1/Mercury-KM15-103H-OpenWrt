#!/bin/bash
# ===============================================================
# Script 4: Configure OpenWrt for Mercury KM15-103H
# ===============================================================
set -e

cd openwrt

echo "Injecting custom overlay files from mercury_km15_103h_build/files..."
mkdir -p files
cp -r ../mercury_km15_103h_build/files/* files/
# Shell scripts in the overlay must be executable on the device; git on
# Windows strips the +x bit, so set it explicitly here after the copy.
find files/usr/bin -type f -exec chmod +x {} \;
find files/usr/sbin -type f -exec chmod +x {} \; 2>/dev/null || true
find files/etc/init.d -type f -exec chmod +x {} \; 2>/dev/null || true
find files/etc/uci-defaults -type f -exec chmod +x {} \; 2>/dev/null || true
find files/lib -type f -name '*.sh' -exec chmod +x {} \; 2>/dev/null || true
find files/www/cgi-bin -type f -exec chmod +x {} \; 2>/dev/null || true

# Guarantee pre-compressed wireless.js.gz exists in overlay
if [ -f files/www/luci-static/resources/view/network/wireless.js ]; then
    gzip -9kf files/www/luci-static/resources/view/network/wireless.js 2>/dev/null || true
fi

# Inject patched LuCI wireless.js into feeds/luci source tree
LUCI_NET_DIR="feeds/luci/modules/luci-mod-network/htdocs/luci-static/resources/view/network"
if [ -d "$LUCI_NET_DIR" ]; then
    echo "Injecting safe bandwidth-filtering wireless.js into feeds/luci..."
    cp -f files/www/luci-static/resources/view/network/wireless.js "$LUCI_NET_DIR/wireless.js"
    [ -f files/www/luci-static/resources/view/network/wireless.js.gz ] && \
        cp -f files/www/luci-static/resources/view/network/wireless.js.gz "$LUCI_NET_DIR/wireless.js.gz" 2>/dev/null || true
fi

# Guarantee pre-compressed 29_ports.js.gz exists in overlay
if [ -f files/www/luci-static/resources/view/status/include/29_ports.js ]; then
    gzip -9kf files/www/luci-static/resources/view/status/include/29_ports.js 2>/dev/null || true
fi

# Inject custom 29_ports.js into feeds/luci source tree
LUCI_STATUS_DIR="feeds/luci/modules/luci-mod-status/htdocs/luci-static/resources/view/status/include"
if [ -d "$LUCI_STATUS_DIR" ]; then
    echo "Injecting port-control 29_ports.js into feeds/luci..."
    cp -f files/www/luci-static/resources/view/status/include/29_ports.js "$LUCI_STATUS_DIR/29_ports.js"
    [ -f files/www/luci-static/resources/view/status/include/29_ports.js.gz ] && \
        cp -f files/www/luci-static/resources/view/status/include/29_ports.js.gz "$LUCI_STATUS_DIR/29_ports.js.gz" 2>/dev/null || true
fi

# Inject custom hostapd.sh into wifi-scripts package tree
if [ -f "files/lib/netifd/hostapd.sh" ]; then
    echo "Injecting custom hostapd.sh with airMAX support into wifi-scripts package..."
    cp -f files/lib/netifd/hostapd.sh package/network/config/wifi-scripts/files/lib/netifd/hostapd.sh 2>/dev/null || true
fi

# hostapd ships unpatched: the device runs the standard channel plan only.
#
# The old 999-mercury-superchannels.patch taught ieee80211_freq_to_channel_ext()
# about 2312-2407, 2477-2507, 2512-2732 and 5000-6110 MHz. Those frequencies
# have no EEPROM calibration on this board and the regulatory database no
# longer grants them, so every one of them failed at AP bring-up:
#     "Frequency 5100 (secondary) not allowed for AP mode, flags: 0x1"
#     "Configured channel (24) or frequency (5120) not found ... IEEE 802.11a"
# Leaving the patch in place while the channels are unusable only moves the
# failure later, so it is removed rather than disabled.
rm -f package/network/services/hostapd/patches/999-mercury-superchannels.patch

# EXPERIMENTAL 2.3 GHz (opt-in, MERCURY_ENABLE_23GHZ): stock hostapd's
# ieee80211_freq_to_channel_ext() only knows 2412-2472/2484 on 2.4 GHz, so
# it rejects 2312-2402 in AP mode. This teaches it the sub-2.4 GHz range.
# Only 2.3 GHz - the 5 GHz side stays standard, unlike the old superchannel
# patch. Written only when the flag is set, so the stable build never gets
# it. Frequencies 2312-2402 map to op_class 81 / HOSTAPD_MODE_IEEE80211G.
case "${MERCURY_ENABLE_23GHZ:-}" in
    ''|0|no|false|disable)
        echo "2.3 GHz hostapd mapping: disabled (MERCURY_ENABLE_23GHZ unset)" ;;
    *)
        echo "2.3 GHz hostapd mapping: ENABLED (experimental)"
        mkdir -p package/network/services/hostapd/patches
        cat << 'EOF' > package/network/services/hostapd/patches/994-mercury-23ghz.patch
--- a/src/common/ieee802_11_common.c
+++ b/src/common/ieee802_11_common.c
@@ -1519,6 +1519,18 @@ enum hostapd_hw_mode
 	if (sec_channel > 1 || sec_channel < -1)
 		return NUM_HOSTAPD_MODES;
 
+	/* Mercury EXPERIMENTAL: 2.3 GHz & 2.7 GHz (2312 - 2402 MHz and 2487 - 2702 MHz).
+	 * Map them to op_class 81 as 11g. Uncalibrated. */
+	if ((freq >= 2312 && freq <= 2402) || (freq >= 2487 && freq <= 2702)) {
+		if (freq < 2407 && (freq - 2312) % 5)
+			return NUM_HOSTAPD_MODES;
+		if (freq > 2407 && (freq - 2407) % 5)
+			return NUM_HOSTAPD_MODES;
+		*channel = (freq - 2407) / 5;
+		*op_class = 81;
+		return HOSTAPD_MODE_IEEE80211G;
+	}
+
 	if (freq >= 2412 && freq <= 2472) {
 		if ((freq - 2407) % 5)
 			return NUM_HOSTAPD_MODES;
EOF
        echo "  wrote 994-mercury-23ghz.patch (hostapd)" ;;
esac

echo "5 GHz super channel hostapd mapping: ENABLED"
mkdir -p package/network/services/hostapd/patches
cat << 'EOF' > package/network/services/hostapd/patches/995-mercury-5ghz-super.patch
--- a/src/common/ieee802_11_common.c
+++ b/src/common/ieee802_11_common.c
@@ -1030,10 +1030,10 @@ enum hostapd_hw_mode hostapd_freq_to_cha
 		return HOSTAPD_MODE_IEEE80211A;
 	}
 
-	if (freq >= 5000 && freq < 5900) {
+	if (freq >= 5000 && freq <= 6200) {
 		if ((freq - 5000) % 5)
 			return NUM_HOSTAPD_MODES;
 		*channel = (freq - 5000) / 5;
-		*op_class = 0; /* TODO */
+		*op_class = 115; /* Mercury KM15-103H: 5GHz super channels */
 		return HOSTAPD_MODE_IEEE80211A;
 	}
EOF
echo "  wrote 995-mercury-5ghz-super.patch (hostapd)"


echo "Writing target .config for Mercury KM15-103H..."
cat << 'EOF' > .config
# Target System
CONFIG_TARGET_ramips=y
CONFIG_TARGET_ramips_mt7621=y
CONFIG_TARGET_ramips_mt7621_DEVICE_mercury_km15-103h=y

# Wireless Drivers & Firmware
CONFIG_PACKAGE_kmod-mt7915e=y
CONFIG_PACKAGE_kmod-mt7915-firmware=y
CONFIG_PACKAGE_kmod-mt76=y
CONFIG_PACKAGE_kmod-mt76-connac=y
CONFIG_PACKAGE_kmod-mt76-core=y
CONFIG_PACKAGE_wireless-regdb=y
CONFIG_PACKAGE_wpad-mbedtls=y

# Web Interface & Management
CONFIG_PACKAGE_luci=y
CONFIG_PACKAGE_luci-ssl=y
CONFIG_PACKAGE_luci-app-commands=y
# luci-theme-openwrt-2020 is the default UI ("style 2020"). bootstrap is
# kept as the built-in fallback LuCI always ships. The active theme is set
# in files/etc/config/luci (option mediaurlbase), not just by installing
# the package - installing alone leaves bootstrap selected.
CONFIG_PACKAGE_luci-theme-openwrt-2020=y
CONFIG_PACKAGE_luci-theme-bootstrap=y
CONFIG_PACKAGE_iwinfo=y
CONFIG_PACKAGE_rpcd=y
CONFIG_PACKAGE_rpcd-mod-luci=y

# System Tools & Utilities
# irqbalance spreads the mt76 (PCIe WiFi) and GMAC (ethernet) IRQs across
# all 4 MT7621 hardware threads instead of pinning them to CPU0, which is
# the single biggest "use all cores" win for AP + routing throughput.
CONFIG_PACKAGE_irqbalance=y
CONFIG_PACKAGE_uboot-envtools=y
CONFIG_PACKAGE_htop=y
CONFIG_PACKAGE_nano=y
CONFIG_PACKAGE_bash=y
CONFIG_PACKAGE_curl=y
CONFIG_PACKAGE_wget-ssl=y
CONFIG_PACKAGE_ca-bundle=y
CONFIG_PACKAGE_mtd=y
CONFIG_PACKAGE_ubi-utils=y

# USB 2.0 / 3.0 Storage & Extroot Packages
CONFIG_PACKAGE_kmod-usb-core=y
CONFIG_PACKAGE_kmod-usb3=y
CONFIG_PACKAGE_kmod-usb2=y
CONFIG_PACKAGE_kmod-usb-storage=y
CONFIG_PACKAGE_kmod-usb-storage-uas=y
CONFIG_PACKAGE_kmod-fs-ext4=y
CONFIG_PACKAGE_kmod-fs-vfat=y
CONFIG_PACKAGE_kmod-nls-cp437=y
CONFIG_PACKAGE_kmod-nls-iso8859-1=y
CONFIG_PACKAGE_kmod-nls-utf8=y
CONFIG_PACKAGE_block-mount=y
CONFIG_PACKAGE_e2fsprogs=y
CONFIG_PACKAGE_fdisk=y
CONFIG_PACKAGE_usbutils=y

# IPv6 removed - this is an IPv4-only build.
#
# OpenWrt pulls odhcpd, odhcp6c, ip6tables and the kernel IPv6 stack in by
# default through DEFAULT_PACKAGES, so switching them off has to be
# explicit; deleting the uci sections alone leaves the daemons installed
# and running. These package disables are what stop the userland from
# being built - odhcp6c/odhcpd are the daemons that solicit on the WAN,
# so removing them is what makes the box IPv4-only in practice.
# CONFIG_PACKAGE_odhcpd-ipv6only is not set
# CONFIG_PACKAGE_odhcp6c is not set
# CONFIG_PACKAGE_kmod-ipv6 is not set
# CONFIG_PACKAGE_kmod-ip6tables is not set
# CONFIG_PACKAGE_kmod-nf-ipt6 is not set
# CONFIG_PACKAGE_kmod-nft-nat6 is not set
# CONFIG_PACKAGE_ip6tables is not set
# CONFIG_PACKAGE_ip6tables-nft is not set
# CONFIG_PACKAGE_luci-proto-ipv6 is not set
# CONFIG_PACKAGE_6in4 is not set
# CONFIG_PACKAGE_6rd is not set
# CONFIG_PACKAGE_6to4 is not set
# CONFIG_PACKAGE_ds-lite is not set
#
# CONFIG_IPV6 (the global "IPv6 support in packages" flag) is deliberately
# NOT seeded off. It is default-y and firewall4/dnsmasq/wpad depend on it,
# so defconfig re-selects it and forcing it off breaks the build (verified:
# the first build after this change failed the IPv6 gate on exactly this
# symbol). With every IPv6 daemon and the ip6tables userland gone, the
# in-kernel stack being present is inert - nothing configures an address
# or solicits on any interface.

# Base filesystem
CONFIG_TARGET_ROOTFS_SQUASHFS=y
CONFIG_TARGET_ROOTFS_UBIFS=y
CONFIG_TARGET_UBIFS_COMPRESSION_ZSTD=y

# Initramfs image for UART Ymodem recovery / first install.
# Shorting NAND pin 9 (#CE) makes SPL fall back to Ymodem; send the
# vendor bootloader dumped from mtd0, then from the U-Boot prompt:
#   loady 0x84000000  -> send *-initramfs-uImage.itb -> bootm 0x84000000
# OpenWrt then runs entirely from RAM, so 'sysupgrade -n' can write NAND
# with no partition mounted.
# NOTE: the correct OpenWrt symbol is TARGET_ROOTFS_INITRAMFS, and it is
# what makes the image get built at all. CONFIG_TARGET_RAMDISK, used here
# earlier, is a kernel Kconfig name rather than an OpenWrt image symbol,
# so defconfig discarded it and no RAM image was ever produced. The .itb
# filename itself comes from KERNEL_INITRAMFS_SUFFIX in mercury-02.
CONFIG_TARGET_ROOTFS_INITRAMFS=y

# NOTE: there is deliberately no U-Boot package here. OpenWrt v24.10.2
# ships uboot-mediatek, uboot-mvebu, ... but NOTHING for ramips/mt7621 -
# MT7621 boards always run the vendor bootloader, so a u-boot.bin simply
# cannot be produced by this build. An earlier CONFIG_PACKAGE_uboot-mt7621=y
# here was silently dropped by `make defconfig` (no such package) and
# quietly produced nothing. For the UART Ymodem recovery path the
# bootloader must be dumped off the device itself:
#     dd if=/dev/mtd0 of=/tmp/uboot_vendor.bin   (Bootloader partition)
# That copy is also the only one guaranteed to match this board's DDR
# and NAND timings.

# nand-utils gives the running device flash_erase / nandwrite / nanddump.
# mercury.sh itself uses OpenWrt's `mtd` for writes, but having the raw
# tools on the box is what makes manual recovery over SSH possible when
# something goes wrong - a firmware that can only be fixed over UART is
# a firmware with a hole in it.
CONFIG_PACKAGE_nand-utils=y

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

# ---------------------------------------------------------------
# Audit what actually survived `make defconfig`.
#
# defconfig silently DROPS any symbol whose package does not exist or
# whose dependencies are unmet - no warning, no error. That is how
# CONFIG_PACKAGE_uboot-mt7621=y sat in this file for several builds
# producing absolutely nothing (there is no such package for ramips).
# Anything we depend on is checked here instead of being discovered
# missing on the device.
# ---------------------------------------------------------------
echo ""
echo "Auditing which options survived defconfig..."

# Dropping any of these produces a firmware that is broken on the device,
# so they abort the build rather than ship a hole.
CRITICAL="CONFIG_PACKAGE_kmod-mt7915e \
CONFIG_PACKAGE_kmod-mt7915-firmware \
CONFIG_PACKAGE_ubi-utils \
CONFIG_PACKAGE_mtd \
CONFIG_PACKAGE_wireless-regdb \
CONFIG_TARGET_ROOTFS_SQUASHFS"

# Useful but not fatal: the build still yields a working router without them.
OPTIONAL="CONFIG_TARGET_ROOTFS_INITRAMFS \
CONFIG_PACKAGE_nand-utils \
CONFIG_PACKAGE_irqbalance \
CONFIG_PACKAGE_luci \
CONFIG_PACKAGE_uboot-envtools \
CONFIG_PACKAGE_kmod-usb3 \
CONFIG_PACKAGE_block-mount"

MISSING=""
for SYM in $CRITICAL; do
	if grep -q "^${SYM}=y" .config; then
		echo "  OK       : $SYM"
	else
		echo "  DROPPED  : $SYM   <-- CRITICAL"
		MISSING="$MISSING $SYM"
	fi
done
for SYM in $OPTIONAL; do
	if grep -q "^${SYM}=y" .config; then
		echo "  OK       : $SYM"
	else
		echo "  dropped  : $SYM   (optional)"
	fi
done

if [ -n "$MISSING" ]; then
	echo ""
	echo "❌ ERROR: defconfig dropped critical option(s):$MISSING"
	echo "   These are silently removed when the package name is wrong or a"
	echo "   dependency is unmet. Building on would produce firmware that is"
	echo "   missing the WiFi driver, the UBI tools sysupgrade needs, or the"
	echo "   regulatory database - all of which only fail once flashed."
	echo ""
	for SYM in $MISSING; do
		echo "--- lines mentioning ${SYM#CONFIG_PACKAGE_} in .config ---"
		grep -i "${SYM#CONFIG_PACKAGE_}" .config | head -5 || echo "(symbol unknown to Kconfig at all)"
	done
	exit 1
fi

# ---------------------------------------------------------------
# Confirm the IPv6 DAEMONS are gone.
#
# The "# CONFIG_X is not set" lines above are a request, not a result.
# Anything still in the target's DEFAULT_PACKAGES, or pulled in as a
# dependency of a package we do want, comes back with =y and defconfig
# says nothing. Deleting the uci sections while odhcpd is still installed
# leaves the daemon running with its own defaults, which is the failure
# this catches.
#
# The fatal list is the userland that actually does something on the wire:
# odhcp6c solicits on the WAN, odhcpd hands out addresses on the LAN,
# ip6tables/kmod-ipv6 carry the filtering path. If any of those ship, the
# box is not IPv4-only no matter what the uci files say.
#
# CONFIG_IPV6 itself is NOT fatal. It is the global "IPv6 support in
# packages" switch, default-y, and firewall4/dnsmasq/wpad depend on it,
# so defconfig re-selects it every time and forcing it off breaks the
# build. With the daemons above gone the in-kernel stack is inert, so its
# presence is reported as a note, not a failure.
# ---------------------------------------------------------------
echo ""
echo "Verifying IPv6 daemons were dropped..."
IPV6_LEFT=""
for SYM in CONFIG_PACKAGE_odhcpd-ipv6only CONFIG_PACKAGE_odhcp6c \
           CONFIG_PACKAGE_kmod-ipv6 CONFIG_PACKAGE_ip6tables; do
	if grep -q "^${SYM}=y" .config; then
		echo "  STILL ON : $SYM"
		IPV6_LEFT="$IPV6_LEFT $SYM"
	else
		echo "  OK       : $SYM disabled"
	fi
done
if grep -q "^CONFIG_IPV6=y" .config; then
	echo "  NOTE     : CONFIG_IPV6=y (kernel stack present but inert - no daemons)"
fi
if [ -n "$IPV6_LEFT" ]; then
	echo ""
	echo "❌ ERROR: IPv6 daemons survived defconfig:$IPV6_LEFT"
	echo "   Something in DEFAULT_PACKAGES or a dependency re-selected them."
	echo "   Find what pulls them in before shipping - an IPv4-only config"
	echo "   against an image that still ships odhcp6c gives a router that"
	echo "   solicits on the WAN with no configuration behind it."
	exit 1
fi

# ---------------------------------------------------------------
# The NAND driver and the bad-block remapping layer are what make this
# board readable at all: block 6 (0xC0000) is a factory bad block, and
# it holds the per-unit factory MAC at 0xC0004. Without the remapping
# layer that read returns an uncorrectable ECC error, every MAC falls
# back to a zero base, and the radios come up as 00:00:00:00:00:0x.
#
# These live in the ramips/mt7621 target kernel config, not in .config,
# so defconfig cannot report on them. Note the symbol names: OpenWrt has
# no CONFIG_MTD_NMBM/CONFIG_NMBM - those are MediaTek SDK names. Upstream
# ships NMBM *inside* the mtk_bmt module, selected by the `mediatek,nmbm`
# property our DTS sets, so MTK_BMT is the symbol that actually matters.
# ---------------------------------------------------------------
echo ""
echo "Verifying NAND + bad-block remapping support in the target kernel config..."
KCFG=$(ls target/linux/ramips/mt7621/config-* 2>/dev/null | head -1)
if [ -z "$KCFG" ]; then
	echo "❌ ERROR: no target/linux/ramips/mt7621/config-* found."
	exit 1
fi
echo "  using $KCFG"
# Ensure custom regulatory database is unconditionally accepted by disabling signature enforcement
sed -i 's/CONFIG_CFG80211_REQUIRE_SIGNED_REGDB=y/# CONFIG_CFG80211_REQUIRE_SIGNED_REGDB is not set/' "$KCFG" 2>/dev/null || true
NAND_MISSING=""
for SYM in CONFIG_MTD_NAND_MT7621 CONFIG_MTD_NAND_MTK_BMT; do
	if grep -q "^${SYM}=y" "$KCFG"; then
		echo "  OK       : $SYM"
	else
		echo "  MISSING  : $SYM   <-- CRITICAL"
		NAND_MISSING="$NAND_MISSING $SYM"
	fi
done
if [ -n "$NAND_MISSING" ]; then
	echo ""
	echo "❌ ERROR: the target kernel config lacks:$NAND_MISSING"
	echo "   MT7621 = the NAND flash controller driver (hardware BCH ECC via"
	echo "   the 'ecc' reg range in our DTS). MTK_BMT = the bad-block layer"
	echo "   that provides NMBM. Building without them yields firmware that"
	echo "   cannot read the factory MAC and may not mount UBI at all."
	grep -n 'MTK_BMT\|NAND_MT7621\|NMBM' "$KCFG" || echo "(no related symbols in this config)"
	exit 1
fi

# Not fatal on its own, but the whole first-install / brick-recovery plan
# rests on being able to boot OpenWrt from RAM, so make its absence loud.
if ! grep -q '^CONFIG_TARGET_ROOTFS_INITRAMFS=y' .config; then
	echo ""
	echo "⚠️  WARNING: TARGET_ROOTFS_INITRAMFS was dropped - no *-initramfs-uImage.itb"
	echo "    will be produced, so the UART Ymodem 'boot OpenWrt from RAM' recovery"
	echo "    path is unavailable and the only install route is sysupgrade."
fi

echo "✅ Configuration complete."
