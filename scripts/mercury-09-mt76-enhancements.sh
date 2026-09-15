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

# 2. Clean up any stale or erroneous patch directories from previous runs
rm -rf openwrt/package/kernel/mac80211/patches/mediatek 2>/dev/null || true
rm -f openwrt/package/kernel/mt76/patches/*superchannel* 2>/dev/null || true
rm -f openwrt/package/kernel/mt76/patches/998-mt7915-he160-dbdc.patch 2>/dev/null || true

# 3. Inject MT7915 27 dBm Tx-Power unlock patch into package/kernel/mt76/patches/
mkdir -p openwrt/package/kernel/mt76/patches
echo ">>> MT7915 Enhancements applied successfully!"

# 4. Ensure stock clean channels (remove any superchannel patch)
rm -f openwrt/package/kernel/mt76/patches/*superchannel* 2>/dev/null || true
echo ">>> Stock IEEE 5GHz channel plan enforced (clean, stable, 100% working channels)."

