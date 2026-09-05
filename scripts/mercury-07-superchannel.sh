#!/bin/bash
# =============================================
# Script 7: Kernel regulatory unlock (mt76 / MT7915E)
# =============================================
# Run from openwrt/build_dir AFTER:
#   make target/linux/prepare
#   make package/kernel/mac80211/prepare
#
# WHAT THIS IS FOR
# ----------------
# This is the FALLBACK path, not the primary one.
#
#   Primary : the 68-channel driver table (999-mercury-superchannels.patch)
#             plus the custom regulatory.db, which every country entry
#             opens to 5115-5930 @ 160 / 33 dBm.
#   Fallback: if regulatory.db fails to load for any reason (signature
#             policy, missing file), cfg80211 falls back to the world
#             regulatory domain compiled into net/wireless/reg.c. These
#             substitutions widen THAT, so the channels stay usable
#             either way.
#
# Because it is the fallback, a pattern that does not match is reported
# loudly but is NOT fatal - the driver table check in
# mercury-05-compile.sh Step 6 is the gate that must never be skipped.
#
# WHAT THIS DELIBERATELY DOES NOT DO
# ----------------------------------
#  * ath/regd.c - Qualcomm-only. mt76 never calls into it; patching it
#    would be a no-op that still looks like success.
#
#  * Deleting the is_valid_rd() rejection block. The widely-copied
#    'sed /if (!is_valid_rd(rd)) {/{N;N;N;N;d}' assumes the block is
#    exactly 5 lines. On kernel 6.6 the pr_err() spans two lines, so the
#    block is 6 lines and the sed deletes 5, leaving an ORPHANED closing
#    brace and a guaranteed compile error. It is also unnecessary: our
#    rules pass is_valid_rd() (5115-5930 is 815 MHz wide, comfortably
#    more than the 160 MHz bandwidth; 2182-2494 is 312 MHz vs 40).
#
#  * mt76's channel table - handled by gen_mt76_patch.py as a real
#    package patch, because an in-place edit here would be undone the
#    next time OpenWrt runs Build/Prepare for the package.
#
#  * wmi.h scan buffers - mt76 uses software scan, so the ath10k -22
#    "too many channels" failure cannot happen here.
# =============================================
set -e

echo "============================================"
echo "=== KERNEL REGULATORY UNLOCK - mt76      ==="
echo "============================================"

ENABLE_23G="${MERCURY_ENABLE_23GHZ:-}"
HITS_TOTAL=0

# --------------------------------------------------------
# PATCH 1: net/wireless/reg.c
#
# Widen the built-in world regulatory domain and clear the
# restriction flags. All plain s/// substitutions - no line
# deletions, nothing that can desynchronise braces.
# --------------------------------------------------------
FOUND_REG=0
for REG in $(find . -path "*/net/wireless/reg.c" 2>/dev/null); do
    FOUND_REG=$((FOUND_REG + 1))
    echo "[PATCH 1] $REG"
    BEFORE=$(md5sum "$REG" | cut -d' ' -f1)

    # Replace world_regdom and strip all restriction flags (NO_IR, DFS, AUTO_BW, NO_OFDM)
    if python3 - "$REG" <<'PYEOF'
import sys, re

path = sys.argv[1]
with open(path, 'r', encoding='utf-8', errors='ignore') as fh:
    text = fh.read()

before = text

# Strip restriction flags everywhere in reg.c
text = re.sub(r'NL80211_RRF_NO_IR\s*\|\s*NL80211_RRF_AUTO_BW', '0', text)
text = re.sub(r'NL80211_RRF_NO_IR', '0', text)
text = re.sub(r'NL80211_RRF_NO_OFDM', '0', text)
text = re.sub(r'NL80211_RRF_DFS', '0', text)

# Widen built-in world_regdom to full 4910-5935 @ 160MHz 30dBm and 2182-2494 @ 40MHz 30dBm
new_world_rules = """static const struct ieee80211_regdomain world_regdom = {
\t.alpha2 = "00",
\t.reg_rules = {
\t\tREG_RULE(2182 - 10, 2494 + 10, 40, 0, 30, 0),
\t\tREG_RULE(4910 - 10, 5935 + 10, 160, 0, 30, 0),
\t},
};"""

world_pat = re.compile(r'static\s+const\s+struct\s+ieee80211_regdomain\s+world_regdom\s*=\s*\{.*?\};', re.DOTALL)
if world_pat.search(text):
    text = world_pat.sub(new_world_rules, text)

if text != before:
    with open(path, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(text)
    print("  -> patched world_regdom and cleared NO_IR/DFS flags")
    sys.exit(0)
else:
    print("  -> already patched or no match")
    sys.exit(1)
PYEOF
    then
        HITS_TOTAL=$((HITS_TOTAL + 1))
    fi
done

if [ "$FOUND_REG" -eq 0 ]; then
    echo "!!!! No net/wireless/reg.c anywhere under build_dir."
    echo "     'make package/kernel/mac80211/prepare' did not unpack the"
    echo "     backports tree, so neither the fallback world domain nor"
    echo "     anything else in this script can be applied."
    exit 1
fi

# --------------------------------------------------------
# PATCH 2: net/wireless/util.c  (only with 2.3 GHz enabled)
#
# ieee80211_channel_to_frequency() maps a 2 GHz channel with
#   2407 + chan * 5
# Channels below 1 are therefore NEGATIVE, and when a channel
# number arrives as an unsigned byte (169 -> 0xA9) the value
# must be reinterpreted as signed for the arithmetic to land
# on 2312-2402 MHz instead of far above the band.
#
# With 2.3 GHz disabled every 2 GHz channel is 1-14, the cast
# is a no-op, and there is no reason to touch the file at all.
#
# Done in Python, not sed: 'sed a\t\ttext' does NOT insert two
# tabs. GNU sed consumes the first backslash and emits a stray
# literal 't', producing "t<TAB>chan = ..." - which is not
# valid C and fails the build. Verified, not assumed.
# --------------------------------------------------------
if [ "$ENABLE_23G" != "0" ] && [ "$ENABLE_23G" != "false" ] && [ "$ENABLE_23G" != "no" ]; then
    echo "[PATCH 2] net/wireless/util.c  (2.3 GHz enabled)"
    for UTIL in $(find . -path "*/net/wireless/util.c" 2>/dev/null); do
        python3 - "$UTIL" <<'PYEOF'
import sys

path = sys.argv[1]
with open(path, encoding='utf-8', errors='ignore') as fh:
    lines = fh.readlines()

MARK = 'chan = (int)(char)chan;'
if any(MARK in ln for ln in lines):
    print('  %s: already patched' % path)
    sys.exit(0)

out = []
done = False
for ln in lines:
    out.append(ln)
    if not done and ln.strip() == 'case NL80211_BAND_2GHZ:':
        # Match the indentation of the case label, plus one level.
        indent = ln[:len(ln) - len(ln.lstrip())]
        out.append(indent + '\t' + MARK + '\n')
        done = True

if not done:
    print('  %s: no "case NL80211_BAND_2GHZ:" found - skipped' % path)
    sys.exit(0)

with open(path, 'w', encoding='utf-8', newline='') as fh:
    fh.writelines(out)
print('  %s: patched' % path)
PYEOF
    done
else
    echo "[PATCH 2] skipped - 2.3 GHz not enabled (MERCURY_ENABLE_23GHZ unset)"
fi

echo "--------------------------------------------"
echo "reg.c files found: $FOUND_REG, modified: $HITS_TOTAL"
echo "Fallback world domain widened. The primary path is the"
echo "68-channel driver table + custom regulatory.db, both of"
echo "which are verified in mercury-05-compile.sh."
