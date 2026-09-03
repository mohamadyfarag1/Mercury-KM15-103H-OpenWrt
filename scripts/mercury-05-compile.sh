#!/bin/bash
# ===============================================================
# Script 5: Compile Firmware for Mercury KM15-103H
# ===============================================================
# Called from the repository root by the CI workflow.
# Orchestrates: regdb, kernel superchannel patches, mt76 channel
# table extension, full build, post-build verification.
# ===============================================================
set -e

# ---------------------------------------------------------------
# Step 1: Generate and inject the custom regulatory database.
# Runs from repo root, copies result into openwrt/files/ so
# OpenWrt bundles it into the squashfs image.
# ---------------------------------------------------------------
echo "======================================="
echo "Step 1: Custom regulatory database..."
echo "======================================="
bash scripts/mercury-06-generate-regdb.sh

cd openwrt

# ---------------------------------------------------------------
# Step 2: Prepare kernel, mac80211 backports, and mt76 sources.
#
# All three must be prepared BEFORE we patch them:
#   - kernel     -> net/wireless/reg.c + util.c
#   - mac80211   -> backports copy of net/wireless/reg.c
#   - mt76       -> mt76/mac80211.c (channel table)
#
# || true: a partial prior run may leave stamps that make prepare
# think it is already done and exit 0; that is fine.
# ---------------------------------------------------------------
echo "======================================="
echo "Step 2: Preparing kernel and wireless sources..."
echo "======================================="
make target/linux/prepare V=s -j"$(nproc)"          2>&1 || true
make package/kernel/mac80211/prepare V=s -j"$(nproc)" 2>&1 || true
make package/kernel/mt76/prepare V=s -j"$(nproc)"   2>&1 || true

# ---------------------------------------------------------------
# Step 3: Extend mt76_channels_5ghz[] to the 68-channel table.
#
# The stock mt76 table has ~28 channels at 20 MHz spacing.
# gen_mt76_patch.py finds the prepared mac80211.c in build_dir,
# replaces the array with 68 channels at 10 MHz spacing (same
# plan as Horus/ath10k: 5180-5885 MHz), generates a unified diff,
# and drops it into package/kernel/mt76/patches/ so OpenWrt
# applies it during Build/Prepare for every future rebuild.
# Then we clean mt76 so the full build re-prepares it from the
# patched source.
# ---------------------------------------------------------------
echo "======================================="
echo "Step 3: Extending mt76 channel table to 68 channels..."
echo "======================================="
python3 ../scripts/gen_mt76_patch.py build_dir

CTPATCH="package/kernel/mt76/patches/999-mercury-superchannels.patch"
if [ ! -s "$CTPATCH" ]; then
    echo "!!!! mt76 superchannel patch was not generated."
    exit 1
fi
echo "Patch: $CTPATCH  ($(wc -l < "$CTPATCH") lines)"

# Clean so mt76 is rebuilt with the patch applied, not from the
# already-prepared (unpatched) tree.
make package/kernel/mt76/clean V=s 2>&1 | tail -5

# ---------------------------------------------------------------
# Step 4: Apply kernel regulatory bypass patches.
#
# Patches net/wireless/reg.c (expand world domain, strip NO_IR /
# NO_OFDM / DFS flags) and net/wireless/util.c (unsigned channel
# arithmetic for channels 169/173/177 coded as > 127).
# Runs from build_dir to find both the kernel tree and the
# mac80211 backports copy in one pass.
# ---------------------------------------------------------------
echo "======================================="
echo "Step 4: Applying extended spectrum patches (kernel reg)..."
echo "======================================="
cd build_dir
bash ../../scripts/mercury-07-superchannel.sh
cd ..

# ---------------------------------------------------------------
# Step 5: Full compilation.
# ---------------------------------------------------------------
echo "======================================="
echo "Step 5: Compiling (this takes ~30 min)..."
echo "======================================="
make -j"$(nproc)" 2>&1 | tee build.log

if [ "${PIPESTATUS[0]}" -ne 0 ]; then
    echo "======================================="
    echo "BUILD FAILED - real compiler output follows"
    echo "======================================="
    FAILED=$(sed -n 's/^ *ERROR: \([^ ]*\) failed to build.*/\1/p' build.log | sort -u)
    if [ -n "$FAILED" ]; then
        for pkg in $FAILED; do
            echo "##### $pkg #####"
            find "logs/$pkg" -name '*.txt' 2>/dev/null | while read -r L; do
                echo "----- $L (last 80 lines) -----"
                tail -n 80 "$L"
            done
        done
    else
        echo "(no 'ERROR: <pkg> failed to build' line; tail of build.log:)"
        tail -n 60 build.log
    fi
    exit 1
fi

# ---------------------------------------------------------------
# Step 6: Verify the shipped mt76 driver carries the extended
# channel table.
#
# After the full build, the mt76 mac80211.c in build_dir reflects
# the patched source. Count CHAN5G() entries to confirm the patch
# was applied (stock ~28, patched 68).
# ---------------------------------------------------------------
echo "======================================="
echo "Step 6: Verifying mt76 channel table in shipped driver..."
echo "======================================="
MT76_MAC=$(find build_dir -name "mac80211.c" \
    -exec grep -l "mt76_channels_5ghz" {} \; 2>/dev/null | head -n1)
if [ -z "$MT76_MAC" ]; then
    echo "!!!! mt76/mac80211.c not found in build_dir after compilation."
    exit 1
fi
CHAN5G_COUNT=$(grep -c 'CHAN5G(' "$MT76_MAC" 2>/dev/null || true)
echo "Shipped mt76 source : $MT76_MAC"
echo "CHAN5G entries      : $CHAN5G_COUNT  (stock ~28, patched 68)"
if [ "${CHAN5G_COUNT:-0}" -lt 60 ]; then
    echo "!!!! Shipped mt76 driver has only $CHAN5G_COUNT CHAN5G entries."
    echo "     The 999-mercury-superchannels.patch did not reach this build."
    echo "     The driver exposes fewer channels than the regdb allows,"
    echo "     so selecting extended channels will fail silently."
    exit 1
fi
echo "OK: shipped mt76 carries the extended $CHAN5G_COUNT-channel table."

# ---------------------------------------------------------------
# Step 7: Verify sysupgrade image exists.
# ---------------------------------------------------------------
echo "======================================="
echo "Step 7: Image sanity check..."
echo "======================================="
BIN_DIR="bin/targets/ramips/mt7621"
IMAGE_FILE=$(find "$BIN_DIR" -type f -name "*mercury_km15-103h*sysupgrade.bin" | head -n 1)
if [ -z "$IMAGE_FILE" ] || [ ! -f "$IMAGE_FILE" ]; then
    echo "!!!! sysupgrade image missing in $BIN_DIR"
    ls -la "$BIN_DIR" 2>/dev/null || true
    exit 1
fi
FILESIZE=$(stat -c%s "$IMAGE_FILE" 2>/dev/null || wc -c < "$IMAGE_FILE")
echo "image : $IMAGE_FILE  ($FILESIZE bytes)"

# ---------------------------------------------------------------
# Step 8: Verify mt7915 firmware made it into the rootfs.
#
# Three blobs are needed: mt7915_rom_patch.bin, mt7915_wa.bin,
# mt7915_wm.bin. A missing blob does not fail the build - it
# fails at probe time on the device, with both radios dead.
# ---------------------------------------------------------------
echo "======================================="
echo "Step 8: Verifying mt7915 firmware in rootfs..."
echo "======================================="
FWDIR=$(find build_dir -type d -name 'mediatek' \
    -path '*/root-*/lib/firmware/mediatek' 2>/dev/null | head -n1)
if [ -z "$FWDIR" ]; then
    echo "!!!! /lib/firmware/mediatek missing from rootfs."
    echo "     Check DEVICE_PACKAGES includes mt7915-firmware."
    exit 1
fi
for FW in mt7915_rom_patch.bin mt7915_wa.bin mt7915_wm.bin; do
    if [ -f "$FWDIR/$FW" ]; then
        echo "  OK: $FW  ($(wc -c < "$FWDIR/$FW") bytes)"
    else
        echo "!!!! $FW MISSING - mt7915e will fail at probe."
        exit 1
    fi
done

# ---------------------------------------------------------------
# Step 9: Verify custom regulatory.db is in the rootfs.
# ---------------------------------------------------------------
echo "======================================="
echo "Step 9: Verifying regulatory.db in rootfs..."
echo "======================================="
REGDB=$(find build_dir -type f \
    -path '*/root-*/lib/firmware/regulatory.db' | head -n1)
if [ -z "$REGDB" ]; then
    echo "!!!! regulatory.db missing from rootfs - extended channels blocked."
    exit 1
fi
REGDB_SZ=$(wc -c < "$REGDB")
if [ "$REGDB_SZ" -lt 5000 ]; then
    echo "WARNING: regulatory.db is $REGDB_SZ bytes - may be the stock file."
    echo "         Expected > 5000 bytes for the all-country unlocked version."
else
    echo "  OK: custom regulatory.db ($REGDB_SZ bytes)"
fi

echo "======================================="
echo "✅ BUILD SUCCESSFUL"
echo "image : $(basename "$IMAGE_FILE")  ($FILESIZE bytes)"
echo "md5   : $(md5sum "$IMAGE_FILE" | awk '{print $1}')"
echo "======================================="

# ---------------------------------------------------------------
# Step 10: Release summary on the CI run page.
# ---------------------------------------------------------------
if [ -n "$GITHUB_STEP_SUMMARY" ]; then
    {
        echo "## Mercury KM15-103H firmware built"
        echo
        echo "commit \`${GITHUB_SHA:0:12}\` on \`${GITHUB_REF_NAME}\`"
        echo
        echo "| image | size | sha256 |"
        echo "|---|---|---|"
        for f in "$BIN_DIR"/*mercury_km15-103h*.bin; do
            [ -f "$f" ] || continue
            printf '| %s | %s | `%s` |\n' \
                "$(basename "$f")" \
                "$(du -h "$f" | cut -f1)" \
                "$(sha256sum "$f" | cut -c1-16)..."
        done
        echo
        echo "Flash \`*-squashfs-sysupgrade.bin\` **without** \"Keep settings\","
        echo "then run \`mercury-wifi-check\` over SSH to confirm the radios came up."
        echo
        echo "mt76 channel table: **$CHAN5G_COUNT channels** (stock ~28, superchannel 68)"
    } >> "$GITHUB_STEP_SUMMARY"
fi
