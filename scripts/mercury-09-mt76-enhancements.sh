#!/bin/bash
# ===============================================================
# Script 9: Apply MT7915 Enhancements (27 dBm Tx-Power unlock)
# ===============================================================
set -e

echo "======================================="
echo "Applying MT7915 Enhancements..."
echo "======================================="

# 1. Create firmware directory (no downloading - use OpenWrt's own bundled blobs)
mkdir -p openwrt/files/lib/firmware/mediatek

# 2. Clean up stale patches from previous runs
rm -rf openwrt/package/kernel/mac80211/patches/mediatek 2>/dev/null || true
rm -f openwrt/package/kernel/mt76/patches/*superchannel* 2>/dev/null || true
rm -f openwrt/package/kernel/mt76/patches/998-mt7915-he160-dbdc.patch 2>/dev/null || true
rm -f openwrt/package/kernel/mt76/patches/995-*.patch 2>/dev/null || true
rm -f openwrt/package/kernel/mt76/patches/993-*.patch 2>/dev/null || true

# 3. Inject MT7915 Tx-Power unlock patch (generated from real source, correct CRLF)
if [ -f "scripts/995-mt7915-power-unlock.patch" ]; then
    cp scripts/995-mt7915-power-unlock.patch openwrt/package/kernel/mt76/patches/995-mt7915-power-unlock.patch
elif [ -f "../scripts/995-mt7915-power-unlock.patch" ]; then
    cp ../scripts/995-mt7915-power-unlock.patch openwrt/package/kernel/mt76/patches/995-mt7915-power-unlock.patch
else
    echo "ERROR: 995-mt7915-power-unlock.patch not found in scripts/ or ../scripts/"
    exit 1
fi
echo ">>> MT7915 Power Unlock patch installed."
echo ">>> MT7915 Enhancements applied successfully!"

# 4. Ensure stock clean channels (remove any superchannel patch)
rm -f openwrt/package/kernel/mt76/patches/*superchannel* 2>/dev/null || true
echo ">>> Stock IEEE 5GHz channel plan enforced (clean, stable, 100% working channels)."
