#!/bin/bash
# ===============================================================
# Script 9: Apply MT7915 Enhancements (27 dBm Tx-Power unlock)
# ===============================================================
set -e

echo "======================================="
echo "Applying MT7915 Enhancements..."
echo "======================================="

# Determine base paths whether running from repo root or openwrt/
if [ -d "openwrt" ]; then
    OWRT_DIR="openwrt"
    SCRIPTS_DIR="scripts"
else
    OWRT_DIR="."
    SCRIPTS_DIR="../scripts"
fi

# 1. Create firmware directory
mkdir -p "$OWRT_DIR/files/lib/firmware/mediatek"

# 2. Clean up stale patches from previous runs
rm -rf "$OWRT_DIR/package/kernel/mac80211/patches/mediatek" 2>/dev/null || true
rm -f "$OWRT_DIR/package/kernel/mt76/patches/"*superchannel* 2>/dev/null || true
rm -f "$OWRT_DIR/package/kernel/mt76/patches/998-mt7915-he160-dbdc.patch" 2>/dev/null || true
rm -f "$OWRT_DIR/package/kernel/mt76/patches/995-"*.patch 2>/dev/null || true
rm -f "$OWRT_DIR/package/kernel/mt76/patches/993-"*.patch 2>/dev/null || true

# 3. Ensure patches directory exists and inject power unlock patch
PATCH_DIR="$OWRT_DIR/package/kernel/mt76/patches"
mkdir -p "$PATCH_DIR"

if [ -f "$SCRIPTS_DIR/995-mt7915-power-unlock.patch" ]; then
    cp "$SCRIPTS_DIR/995-mt7915-power-unlock.patch" "$PATCH_DIR/995-mt7915-power-unlock.patch"
    echo ">>> MT7915 Power Unlock patch installed to $PATCH_DIR/995-mt7915-power-unlock.patch"
elif [ -f "scripts/995-mt7915-power-unlock.patch" ]; then
    cp "scripts/995-mt7915-power-unlock.patch" "$PATCH_DIR/995-mt7915-power-unlock.patch"
    echo ">>> MT7915 Power Unlock patch installed to $PATCH_DIR/995-mt7915-power-unlock.patch"
else
    echo "WARNING: 995-mt7915-power-unlock.patch not found in $SCRIPTS_DIR or scripts/"
fi

echo ">>> MT7915 Enhancements applied successfully!"

# 4. Ensure stock clean channels (remove any superchannel patch)
rm -f "$PATCH_DIR/"*superchannel* 2>/dev/null || true
echo ">>> Stock IEEE 5GHz channel plan enforced (clean, stable, 100% working channels)."
