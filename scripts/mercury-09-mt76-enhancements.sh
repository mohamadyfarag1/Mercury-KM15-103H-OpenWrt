#!/bin/bash
# ===============================================================
# Script 9: Apply MT7915 Enhancements (Firmware + 27 dBm Tx-Power)
# ===============================================================
set -e

echo "======================================="
echo "Applying MT7915 Enhancements..."
echo "======================================="

# 1. Update MT7915 Firmware blobs to latest from Linux-Firmware upstream
mkdir -p openwrt/files/lib/firmware/mediatek
echo "Downloading latest MT7915 firmware blobs..."
wget -qO openwrt/files/lib/firmware/mediatek/mt7915_wa.bin "https://git.kernel.org/pub/scm/linux/kernel/git/firmware/linux-firmware.git/plain/mediatek/mt7915_wa.bin"
wget -qO openwrt/files/lib/firmware/mediatek/mt7915_wm.bin "https://git.kernel.org/pub/scm/linux/kernel/git/firmware/linux-firmware.git/plain/mediatek/mt7915_wm.bin"
wget -qO openwrt/files/lib/firmware/mediatek/mt7915_rom_patch.bin "https://git.kernel.org/pub/scm/linux/kernel/git/firmware/linux-firmware.git/plain/mediatek/mt7915_rom_patch.bin"
chmod 644 openwrt/files/lib/firmware/mediatek/mt7915*.bin
echo "Latest MT7915 firmware blobs installed to openwrt/files/lib/firmware/mediatek/"

# 2. Clean up any stale or erroneous patch directories from previous runs
rm -rf openwrt/package/kernel/mac80211/patches/mediatek 2>/dev/null || true
rm -f openwrt/package/kernel/mt76/patches/*superchannel* 2>/dev/null || true
rm -f openwrt/package/kernel/mt76/patches/998-mt7915-he160-dbdc.patch 2>/dev/null || true

# 3. Inject MT7915 27 dBm Tx-Power unlock patch into package/kernel/mt76/patches/
mkdir -p openwrt/package/kernel/mt76/patches
cat << 'EOF' > openwrt/package/kernel/mt76/patches/995-mt7915-power-27dbm.patch
--- a/mt7915/init.c
+++ b/mt7915/init.c
@@ -307,9 +307,8 @@
 							  target_power);
 		target_power += nss_delta;
 		target_power = DIV_ROUND_UP(target_power, 2);
-		chan->max_power = min_t(int, chan->max_reg_power,
-					target_power);
-		chan->orig_mpwr = target_power;
+		chan->max_power = chan->max_reg_power;
+		chan->orig_mpwr = chan->max_reg_power;
 	}
 }
 
EOF

echo ">>> MT7915 27 dBm power unlock patch installed to openwrt/package/kernel/mt76/patches/995-mt7915-power-27dbm.patch"
echo ">>> MT7915 Enhancements applied successfully!"

# 4. Inject Superchannels Patch
if [ -f "scripts/999-mt76-5ghz-custom-superchannels.patch" ]; then
    cp scripts/999-mt76-5ghz-custom-superchannels.patch openwrt/package/kernel/mt76/patches/
    echo ">>> Superchannels patch (5000-5995 MHz) installed."
else
    echo "WARNING: scripts/999-mt76-5ghz-custom-superchannels.patch not found!"
fi
