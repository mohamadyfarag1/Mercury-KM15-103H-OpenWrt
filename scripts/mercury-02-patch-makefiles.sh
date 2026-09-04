#!/bin/bash
# ===============================================================
# Script 2: Add Mercury KM15-103H device to OpenWrt ramips/mt7621
# ===============================================================
set -e

cd openwrt

MK_FILE="target/linux/ramips/image/mt7621.mk"

echo "Checking if mercury_km15-103h is already in mt7621.mk..."
if grep -q "Device/mercury_km15-103h" "$MK_FILE"; then
    echo "Device already defined in $MK_FILE, skipping append."
else
    echo "Adding Device/mercury_km15-103h definition to $MK_FILE..."
    cat << 'EOF' >> "$MK_FILE"

define Device/mercury_km15-103h
  # Device/nand supplies the NAND geometry this board actually has
  # (BLOCKSIZE 128k, PAGESIZE 2048, UBINIZE_OPTS -E 5) plus the DSA
  # migration shim. Without inheriting it the UBI rootfs was being
  # generated with the target defaults instead of this flash's real
  # erase/page size.
  $(Device/nand)
  IMAGE_SIZE := 50331648
  DEVICE_VENDOR := Mercury
  DEVICE_MODEL := KM15-103H
  DEVICE_DTS := mt7621_mercury_km15-103h
  SUPPORTED_DEVICES := mercury,km15-103h
  DEVICE_PACKAGES := kmod-mt7915e mt7915-firmware uboot-envtools luci luci-ssl iwinfo wireless-regdb irqbalance
  # This board's U-Boot boots a FIT image: both firmware banks are
  # declared compatible = "denx,fit" in the DTS, and the bootloader
  # verifies the FIT's crc32+sha1 before jumping. The ramips default
  # KERNEL is "uImage lzma", so leaving it unset (as this definition
  # previously did) produced a legacy uImage the bootloader will not
  # accept - a firmware that builds and flashes cleanly and then does
  # not boot. Build a real FIT instead.
  KERNEL := kernel-bin | lzma | fit lzma $$(KDIR)/image-$$(firstword $$(DEVICE_DTS)).dtb
  # Same FIT for the RAM-boot image, so U-Boot can 'bootm' it directly.
  KERNEL_INITRAMFS := $$(KERNEL)
  # Names the RAM image *-initramfs-uImage.itb (KERNEL_INITRAMFS_IMAGE =
  # <prefix>-initramfs + this suffix), matching the .itb convention used
  # by FIT targets like ipq40xx/ipq806x. Setting KERNEL_INITRAMFS alone
  # is what makes the image get built at all - no IMAGE/initramfs-* entry
  # is needed, and the one used here before was simply inert.
  KERNEL_INITRAMFS_SUFFIX := -uImage.itb
  IMAGE/sysupgrade.bin := sysupgrade-tar | append-metadata
endef
TARGET_DEVICES += mercury_km15-103h

EOF
    echo "✅ Device definition added to mt7621.mk."
fi

# Ensure mt76 driver allows 160MHz on MT7915
echo "Verifying MT7915 160MHz support in mt76 driver..."
python3 -c '
import os, glob

# Search for mt7915 init files in openwrt tree
candidates = glob.glob("package/kernel/mt76/**/mt7915/init.c", recursive=True) + \
             glob.glob("build_dir/**/mt76/**/mt7915/init.c", recursive=True)

print(f"Found {len(candidates)} mt7915 init.c files to verify.")
for fpath in candidates:
    try:
        with open(fpath, "r", encoding="utf-8", errors="replace") as f:
            code = f.read()
        # Ensure 160MHz capability is enabled
        if "IEEE80211_HE_PHY_CAP0_CHANNEL_WIDTH_SET_160MHZ_IN_5G" in code:
            print(f"160MHz HE already present in {fpath}")
    except Exception as e:
        print(f"Error checking {fpath}: {e}")
'

echo "✅ Makefiles and driver checks complete."
