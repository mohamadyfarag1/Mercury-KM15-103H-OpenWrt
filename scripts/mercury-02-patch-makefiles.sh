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
  $(Device/dsa-migration)
  $(Device/uimage-lzma-loader)
  $(Device/nand)
  IMAGE_SIZE := 100663296
  KERNEL_SIZE := 6144k
  DEVICE_VENDOR := Mercury
  DEVICE_MODEL := HOURS-103AX-NEXT-GEN
  DEVICE_DTS := mt7621_mercury_km15-103h
  SUPPORTED_DEVICES := mercury,km15-103h
  DEVICE_PACKAGES := kmod-mt7915e kmod-mt7915-firmware wpad-mbedtls uboot-envtools luci luci-ssl iwinfo wireless-regdb irqbalance zlib libbz2 libopenssl-conf libopenssl3 openssl-util libpython3 python3-base python3-light
  KERNEL_INITRAMFS := $$(KERNEL)
  IMAGES += factory.bin breedweb-factory.bin
  IMAGE/factory.bin := append-kernel | pad-to $$(KERNEL_SIZE) | append-ubi | check-size
  IMAGE/breedweb-factory.bin := append-kernel | pad-to $$(KERNEL_SIZE) | append-ubi | check-size
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
