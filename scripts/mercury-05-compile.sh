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
#
# 2.3 GHz (2312-2402 MHz) is OFF by default. Set MERCURY_ENABLE_23GHZ=1
# in the environment to include it - see the note in gen_mt76_patch.py
# for why it is opt-in rather than always on.
# ---------------------------------------------------------------
echo "======================================="
echo "Step 3: Extending mt76 channel table to 68 channels..."
echo "======================================="
echo "MERCURY_ENABLE_23GHZ = '${MERCURY_ENABLE_23GHZ:-(unset - 2.3 GHz disabled)}'"
python3 ../scripts/gen_mt76_patch.py build_dir

CTPATCH="package/kernel/mt76/patches/999-mercury-superchannels.patch"
if [ ! -s "$CTPATCH" ]; then
    echo "!!!! mt76 superchannel patch was not generated."
    exit 1
fi
echo "Patch: $CTPATCH  ($(wc -l < "$CTPATCH") lines)"

# Force mt76 to be re-extracted AND re-patched on the next build.
#
# `make package/kernel/mt76/clean` for a KERNEL package only removes the
# install stamps (.mt76_installed, mt76.list) - it leaves the extracted
# source tree and its ".prepared_<hash>" stamp in place. With that stamp
# present, the full build in Step 5 SKIPS the Prepare (extract+patch)
# phase entirely, so the just-generated 999 patch is never applied and
# the driver ships the stock 28-channel table (this is exactly the
# "patch did not reach this build" failure seen on run 7f446af).
#
# Deleting the prepared source dir removes that stamp, so the next `make`
# re-extracts mt76 from the tarball and applies every patch in patches/
# in order - including 999-mercury-superchannels.patch, which is a diff
# against the fully-prepared tree and therefore applies cleanly as the
# last patch.
make package/kernel/mt76/clean V=s 2>&1 | tail -5
echo "Forcing mt76 re-extract by removing the prepared source dir(s):"
rm -rfv build_dir/target-*/linux-*/mt76-* 2>/dev/null | tail -3
if ls build_dir/target-*/linux-*/mt76-* >/dev/null 2>&1; then
    echo "!!!! mt76 source dir still present after removal - re-patch may be skipped."
    exit 1
fi
echo "OK: mt76 prepared source removed; Step 5 will re-extract and apply 999."

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
# Count only real array entries - CHAN5G(36, 5180). A plain
# grep -c 'CHAN5G(' also counts the "#define CHAN5G(_idx, _freq)"
# macro and reports 69 for a 68-channel table, which is exactly the
# kind of off-by-one that turns a threshold check into a coin flip.
CHAN5G_COUNT=$(grep -cE 'CHAN5G\(-?[0-9]+, *[0-9]+\)' "$MT76_MAC" 2>/dev/null || true)
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

# ---------------------------------------------------------------
# Step 9.5: Verify the UBI tools mercury.sh now depends on are in the
# rootfs, and that the sysupgrade tar actually carries BOTH "kernel"
# and "root" members.
#
# mercury_do_upgrade() writes the rootfs via `ubiupdatevol` because
# this device's two "firmware" banks share a single UBI rootfs volume
# regardless of which bank's kernel booted (verified on real hardware,
# 2026-09-03: booting bank 2's kernel still shows "ubi0: attached
# mtd5", bank 1's ubi). Without ubiattach/ubiupdatevol/ubinfo present,
# RAMFS_COPY_BIN cannot stage them into the upgrade ramdisk and every
# upgrade attempt fails at the "Writing new rootfs" step - discovered
# the hard way on the very first real-device test of this build, where
# the earlier kernel-only upgrade left the device running a new kernel
# against the old vendor rootfs. Catch a missing package here instead.
# ---------------------------------------------------------------
echo "======================================="
echo "Step 9.5: Verifying UBI tools + sysupgrade tar structure..."
echo "======================================="
ROOTDIR=$(find build_dir -type d -path '*/root-ramips*' 2>/dev/null | head -n1)
if [ -z "$ROOTDIR" ]; then
    echo "!!!! could not find the root-ramips staging directory under build_dir."
    find build_dir -maxdepth 3 -type d -name 'root-*' 2>/dev/null
    exit 1
fi
echo "rootfs staging dir: $ROOTDIR"
for TOOL in ubiattach ubidetach ubiupdatevol ubiformat ubimkvol ubinfo; do
    if find "$ROOTDIR" -type f -name "$TOOL" 2>/dev/null | grep -q .; then
        echo "  OK: $TOOL present in rootfs"
    else
        echo "!!!! $TOOL missing from rootfs - mercury_do_upgrade() cannot run."
        echo "     ubi-utils package should provide this; check DEVICE_PACKAGES / feeds."
        exit 1
    fi
done

TAR_IMAGE=$(find "$BIN_DIR" -type f -name "*mercury_km15-103h*sysupgrade.bin" | head -n1)
KERNEL_MEMBER=$(tar -tf "$TAR_IMAGE" 2>/dev/null | grep '/kernel$')
ROOT_MEMBER=$(tar -tf "$TAR_IMAGE" 2>/dev/null | grep '/root$')
if [ -z "$KERNEL_MEMBER" ] || [ -z "$ROOT_MEMBER" ]; then
    echo "!!!! sysupgrade tar is missing 'kernel' and/or 'root':"
    tar -tf "$TAR_IMAGE" 2>/dev/null
    echo "     mercury_do_upgrade() requires both - see the comment above"
    echo "     mercury_find_ubi_rootfs_dev() in lib/upgrade/mercury.sh for why."
    exit 1
fi
echo "  OK: sysupgrade tar has both '$KERNEL_MEMBER' and '$ROOT_MEMBER'"

echo "======================================="
echo "✅ BUILD SUCCESSFUL"
echo "image : $(basename "$IMAGE_FILE")  ($FILESIZE bytes)"
echo "md5   : $(md5sum "$IMAGE_FILE" | awk '{print $1}')"
echo "======================================="

# ---------------------------------------------------------------
# Step 9.7: Collect recovery files (u-boot binary + initramfs image)
# into a single directory so CI can upload them as one artifact.
#
# u-boot binary: needed to respond to the SPL Ymodem prompt when
#   NAND CE# is shorted. SPL loads it into RAM → interactive U-Boot
#   console → loady 0x84000000 → bootm → OpenWrt in RAM.
#
# initramfs-kernel.bin: OpenWrt running 100% from RAM. From SSH,
#   run 'sysupgrade -n <image.bin>' to write to NAND permanently,
#   or erase+repartition NAND before flashing.
# ---------------------------------------------------------------
echo "======================================="
echo "Step 9.7: Collecting UART recovery files..."
echo "======================================="
RECOVERY_DIR="../recovery_files"
mkdir -p "$RECOVERY_DIR"

# Find u-boot binary (built by CONFIG_PACKAGE_uboot-mt7621)
UBOOT_BIN=$(find build_dir -name "u-boot.bin" \
    -path "*/uboot-mt7621*" 2>/dev/null | head -n1)
if [ -n "$UBOOT_BIN" ]; then
    cp "$UBOOT_BIN" "$RECOVERY_DIR/u-boot-mt7621.bin"
    echo "  OK: u-boot binary  ($(wc -c < "$RECOVERY_DIR/u-boot-mt7621.bin") bytes)"
else
    echo "  WARN: u-boot-mt7621.bin not found - check CONFIG_PACKAGE_uboot-mt7621=y"
fi

# Find initramfs kernel image
INITRAMFS=$(find "$BIN_DIR" -name "*mercury_km15-103h*initramfs*" 2>/dev/null | head -n1)
if [ -n "$INITRAMFS" ]; then
    cp "$INITRAMFS" "$RECOVERY_DIR/$(basename "$INITRAMFS")"
    echo "  OK: initramfs image ($(wc -c < "$INITRAMFS") bytes)"
else
    echo "  WARN: initramfs-kernel.bin not found"
    echo "        Add KERNEL_INITRAMFS + IMAGE/initramfs-kernel.bin to device def"
fi

# Write the U-Boot boot commands to a README
cat > "$RECOVERY_DIR/HOW_TO_USE.txt" << 'HOWTO'
Mercury KM15-103H UART Recovery Procedure
==========================================

STEP 1 - Get U-Boot running in RAM:
  1. Connect UART (115200 8N1) + Tera Term
  2. Power on the device
  3. When SPL starts printing, short NAND Pin 9 (#CE) to GND
  4. Wait for: "Accepted mode is Ymodem-1K."
  5. In Tera Term: File > Transfer > YMODEM > Send > pick u-boot-mt7621.bin
  6. U-Boot boots into RAM -> you get a "#" prompt

STEP 2 - Load OpenWrt initramfs into RAM:
  At the U-Boot "#" prompt:
    loady 0x84000000
  In Tera Term: File > Transfer > YMODEM > Send -> pick *-initramfs-kernel.bin
  Then:
    bootm 0x84000000
  OpenWrt boots from RAM (no NAND mounted).

STEP 3 - Flash to NAND permanently:
  SSH into 192.168.1.1 (default IP in initramfs):
    scp *-sysupgrade.bin root@192.168.1.1:/tmp/
    ssh root@192.168.1.1 "sysupgrade -n /tmp/*-sysupgrade.bin"

STEP 4 (OPTIONAL) - Erase and repartition NAND before flashing:
  From initramfs SSH (DANGER - erases everything except Bootloader/Factory):
    flash_erase /dev/mtd2 0 0   # Config
    flash_erase /dev/mtd3 0 0   # firmware
    flash_erase /dev/mtd4 0 0   # firmware2
    flash_erase /dev/mtd5 0 0   # Userdata
  Then do sysupgrade as in Step 3.

NOTE: NEVER erase /dev/mtd0 (Bootloader) or /dev/mtd1 (Factory).
      Factory contains WiFi calibration - losing it kills the radio.
HOWTO
echo "  OK: HOW_TO_USE.txt written"

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
