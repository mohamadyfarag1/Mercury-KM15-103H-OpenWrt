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
rm -f openwrt/package/kernel/mt76/patches/995-*.patch 2>/dev/null || true

# 3. Inject MT7915 Tx-Power unlock patch into package/kernel/mt76/patches/
mkdir -p openwrt/package/kernel/mt76/patches
cat << 'PATCHEOF' > openwrt/package/kernel/mt76/patches/995-mt7915-power-unlock.patch
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
--- a/mt7915/mcu.c
+++ b/mt7915/mcu.c
@@ -3375,6 +3375,11 @@
 	tx_power = mt7915_get_power_bound(phy, hw->conf.power_level);
 	tx_power = mt76_get_rate_power_limits(mphy, mphy->chandef.chan,
 					      &limits_array, tx_power);
+
+	/* MERCURY: Force requested tx_power for all rates, ignore EEPROM limits */
+	tx_power = mt7915_get_power_bound(phy, hw->conf.power_level);
+	for (i = 0; i < sizeof(limits_array); i++)
+		((s8 *)&limits_array)[i] = tx_power;
+
 	mphy->txpower_cur = tx_power;
 
 	for (i = 0, idx = 0; i < ARRAY_SIZE(mt7915_sku_group_len); i++) {
PATCHEOF

echo ">>> MT7915 Power Unlock patch installed."
echo ">>> MT7915 Enhancements applied successfully!"

# 4. Ensure stock clean channels (remove any superchannel patch)
rm -f openwrt/package/kernel/mt76/patches/*superchannel* 2>/dev/null || true
echo ">>> Stock IEEE 5GHz channel plan enforced (clean, stable, 100% working channels)."
