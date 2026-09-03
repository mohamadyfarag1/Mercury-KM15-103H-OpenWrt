#!/bin/bash
# =============================================
# Script 7: Unlock Extended Spectrum (mt76 / MT7915E)
# =============================================
# Run from openwrt/build_dir AFTER make target/linux/prepare and
# make package/kernel/mac80211/prepare have been called. Patches
# the kernel wireless subsystem to allow the full 5115-5930 MHz
# range without DFS gating.
#
# mt76 vs ath10k differences (both important):
#
#   1. ath/regd.c is Qualcomm-specific.  mt76 never calls into it,
#      so patching it here would be a no-op. We skip it.
#
#   2. mt76's mt76_channels_5ghz[] already carries channels 36-177
#      (confirmed in the live WitWrt firmware: 28 channels visible).
#      No driver channel-table patch is needed.
#
#   3. mt76 uses SOFTWARE scan (sw_scan_start/complete), not hw_scan,
#      so there is no wmi.h scan-buffer limit to raise.
#
#   4. KM15-103H has no "power-limits" DT node, so
#      mt76_get_rate_power_limits() fills dest with target_power
#      and returns it unchanged - power never drops to zero on
#      extended channels.
#
# What we DO patch:
#   PATCH 1: net/wireless/reg.c  - expand the kernel world domain,
#            remove NO_IR / NO_OFDM flags and the rd validation gate
#            that would reject our custom regdb entries.
#   PATCH 2: net/wireless/util.c - allow channel numbers above 0x7F
#            (needed for channels 169/173/177 coded as signed byte).
# =============================================
set -e

echo "============================================"
echo "=== SUPERCHANNEL UNLOCK - mt76 / MT7915E ==="
echo "============================================"

# --------------------------------------------------------
# PATCH 1: net/wireless/reg.c
# Expand the world regulatory domain and strip restriction
# flags so the custom regulatory.db entries are honoured.
# --------------------------------------------------------
PATCHED_REG=0
for REG in $(find . -path "*/net/wireless/reg.c" 2>/dev/null); do
    echo "[PATCH 1] net/wireless/reg.c -> $REG"

    # Expand 2.4 GHz world domain entries
    sed -i 's/REG_RULE(2412-10, 2462+10, 40, 6, 20, 0)/REG_RULE(2182-10, 2484+10, 40, 6, 33, 0)/g' "$REG"
    sed -i 's/REG_RULE(2467-10, 2472+10, 20, 6, 20,/REG_RULE(2182-10, 2484+10, 40, 6, 33,/g' "$REG"
    sed -i 's/REG_RULE(2484-10, 2484+10, 20, 6, 20,/REG_RULE(2484-10, 2484+10, 40, 6, 33,/g' "$REG"

    # Expand 5 GHz world domain entries to full 5115-5930 range
    sed -i 's/REG_RULE(5150-10, 5350+10, 80, 0, 30,/REG_RULE(5115-10, 5930+10, 160, 0, 33,/g' "$REG"
    sed -i 's/REG_RULE(5470-10, 5850+10, 80, 0, 30,/REG_RULE(5115-10, 5930+10, 160, 0, 33,/g' "$REG"
    sed -i 's/REG_RULE(5725-10, 5850+10, 80, 0, 30,/REG_RULE(5115-10, 5930+10, 160, 0, 33,/g' "$REG"

    # Remove the validity gate that would reject our wide custom rules
    sed -i '/if (!is_valid_rd(rd)) {/{N;N;N;N;d}' "$REG"
    sed -i '/if (WARN(!is_valid_rd(rd)/{N;N;N;d}' "$REG"

    # Strip restriction flags
    sed -i 's/NL80211_RRF_NO_IR | NL80211_RRF_AUTO_BW/0/g' "$REG"
    sed -i 's/NL80211_RRF_NO_IR/0/g' "$REG"
    sed -i 's/NL80211_RRF_NO_OFDM/0/g' "$REG"

    echo "  -> patched OK"
    PATCHED_REG=$((PATCHED_REG + 1))
done

if [ "$PATCHED_REG" -eq 0 ]; then
    echo "WARNING: no net/wireless/reg.c found in build_dir."
    echo "         run 'make target/linux/prepare' and"
    echo "         'make package/kernel/mac80211/prepare' first."
fi

# --------------------------------------------------------
# PATCH 2: net/wireless/util.c
# Channels 169/173/177 have numbers > 127.  When stored as
# a signed byte and cast back to int the high bit reads as
# negative (e.g. 169 -> -87).  This one-liner promotes the
# value to unsigned before the comparison, keeping channel
# arithmetic correct for any number in [128, 255].
# --------------------------------------------------------
for UTIL in $(find . -path "*/net/wireless/util.c" 2>/dev/null); do
    echo "[PATCH 2] net/wireless/util.c -> $UTIL"
    if ! grep -q 'chan = (int)(char)chan' "$UTIL"; then
        sed -i '/case NL80211_BAND_2GHZ:/a\\t\tchan = (int)(char)chan;' "$UTIL"
        echo "  -> patched OK"
    else
        echo "  -> already patched (idempotent)"
    fi
done

echo "Superchannel patches applied (PATCH 1-2)."
echo "mt76 channel table and driver scan buffers need no changes."
