#!/bin/bash
# ===============================================================
# Script 5: Compile Firmware for Mercury KM15-103H
# ===============================================================
# Called from the repository root by the CI workflow.
# Orchestrates: regdb, kernel superchannel patches, full build,
# post-build verification.
# ===============================================================
set -e

# ---------------------------------------------------------------
# Step 1: Generate and inject the custom regulatory database.
#
# This runs before cd openwrt so it can create the wireless-regdb
# clone in the repo root and copy the result into openwrt/files/.
# The file must be in place BEFORE compilation so OpenWrt bundles
# it into the squashfs image.
# ---------------------------------------------------------------
echo "======================================="
echo "Step 1: Custom regulatory database..."
echo "======================================="
bash scripts/mercury-06-generate-regdb.sh

cd openwrt

# ---------------------------------------------------------------
# Step 2: Prepare kernel + mac80211 sources so the next step
# can patch reg.c / util.c in build_dir.  || true because a
# partial prior run might leave stamps that make prepare think
# it is already done and exit 0 anyway.
# ---------------------------------------------------------------
echo "======================================="
echo "Step 2: Preparing kernel sources..."
echo "======================================="
make target/linux/prepare V=s -j"$(nproc)" 2>&1 || true
make package/kernel/mac80211/prepare V=s -j"$(nproc)" 2>&1 || true

# ---------------------------------------------------------------
# Step 3: Apply kernel regulatory bypass patches.
#
# The script runs from build_dir and walks the tree to find
# net/wireless/reg.c and net/wireless/util.c wherever the
# mac80211 backport or the kernel itself extracted them.
# ---------------------------------------------------------------
echo "======================================="
echo "Step 3: Applying extended spectrum patches..."
echo "======================================="
cd build_dir
bash ../../scripts/mercury-07-superchannel.sh
cd ..

# ---------------------------------------------------------------
# Step 4: Full compilation.  tee to build.log so the CI step
# summary can scan it on failure, but also stream to stdout.
# ---------------------------------------------------------------
echo "======================================="
echo "Step 4: Compiling (this takes ~30 min)..."
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
        echo "(no ERROR: <pkg> line in build.log; tail:)"
        tail -n 60 build.log
    fi
    exit 1
fi

# ---------------------------------------------------------------
# Step 5: Verify the sysupgrade image exists and is non-empty.
# ---------------------------------------------------------------
echo "======================================="
echo "Step 5: Image sanity check..."
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
# Step 6: Verify mt7915 firmware made it into the rootfs.
#
# mt7915 needs three files from the mt7915-firmware package:
#   mt7915_rom_patch.bin, mt7915_wa.bin, mt7915_wm.bin
# They live in /lib/firmware/mediatek/ in the running system.
# A missing firmware file does NOT fail the build - it fails at
# driver probe time on the device, with "mt7915: fail to load
# firmware" and both radios dead. Assert here instead.
# ---------------------------------------------------------------
echo "======================================="
echo "Step 6: Verifying mt7915 firmware in rootfs..."
echo "======================================="
FWDIR=$(find build_dir -type d -name 'mediatek' -path '*/root-*/lib/firmware/mediatek' 2>/dev/null | head -n1)
if [ -z "$FWDIR" ]; then
    echo "!!!! /lib/firmware/mediatek missing from rootfs build_dir."
    echo "     Check that DEVICE_PACKAGES (02-patch-makefiles.sh) and"
    echo "     .config both include mt7915-firmware."
    exit 1
fi
echo "rootfs firmware dir : $FWDIR"
for FW in mt7915_rom_patch.bin mt7915_wa.bin mt7915_wm.bin; do
    if [ -f "$FWDIR/$FW" ]; then
        echo "  OK: $FW  ($(wc -c < "$FWDIR/$FW") bytes)"
    else
        echo "!!!! $FW is MISSING from the rootfs."
        echo "     The mt7915e driver will fail at probe with both radios down."
        exit 1
    fi
done

# ---------------------------------------------------------------
# Step 7: Verify custom regulatory.db is in the rootfs.
#
# Without it, channels 12/13/14 at 2.4 GHz stay disabled and
# 5 GHz channels above 165 are blocked or limited in power.
# ---------------------------------------------------------------
echo "======================================="
echo "Step 7: Verifying regulatory.db in rootfs..."
echo "======================================="
REGDB=$(find build_dir -type f -path '*/root-*/lib/firmware/regulatory.db' | head -n1)
if [ -z "$REGDB" ]; then
    echo "!!!! regulatory.db missing from rootfs - extended channels blocked."
    exit 1
fi
REGDB_SZ=$(wc -c < "$REGDB")
echo "regulatory.db : $REGDB  ($REGDB_SZ bytes)"
# Stock wireless-regdb from OpenWrt is typically 2-4 KB. Our custom
# all-country unlocked one is larger (each country gets two rules).
# Warn if it looks like the stock file ended up in the image.
if [ "$REGDB_SZ" -lt 5000 ]; then
    echo "WARNING: regulatory.db is only $REGDB_SZ bytes - may be the stock"
    echo "         (restricted) database rather than our custom one."
    echo "         Expected > 5000 bytes for the all-country unlocked version."
else
    echo "  OK: custom regulatory.db ($REGDB_SZ bytes) is in the image."
fi

echo "======================================="
echo "✅ BUILD SUCCESSFUL"
echo "image : $(basename "$IMAGE_FILE")  ($FILESIZE bytes)"
echo "md5   : $(md5sum "$IMAGE_FILE" | awk '{print $1}')"
echo "======================================="

# ---------------------------------------------------------------
# Step 8: Release summary for the CI run page.
#
# Checksums here are the ones to compare after downloading the
# artifact - a truncated download flashes as willingly as a good
# one and only fails once it is on the device.
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
    } >> "$GITHUB_STEP_SUMMARY"
fi
