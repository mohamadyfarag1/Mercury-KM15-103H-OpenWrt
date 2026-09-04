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
# The build tree contains TWO copies of mt76:
#   1. the kernel's own in-tree driver, under
#      build_dir/toolchain-*/linux-*/drivers/net/wireless/mediatek/mt76/
#      - part of the kernel source but NOT built (OpenWrt disables the
#        in-tree driver and uses the package instead), so it always
#        shows the stock 28 channels;
#   2. the mt76 PACKAGE, at build_dir/target-*/linux-*/mt76-<version>/
#      - the git snapshot kmod-mt7915e is actually compiled from, and
#        the only tree 999-mercury-superchannels.patch targets.
# A bare `find build_dir -name mac80211.c | head -1` returns whichever
# the filesystem hands back first. On run b615d33 that was the unused
# in-tree copy, so the check reported 28 and failed the build even
# though the package tree is the one that matters. Pin to the package.
MT76_PKG_DIR=$(ls -d build_dir/target-*/linux-*/mt76-* 2>/dev/null | head -n1)
if [ -z "$MT76_PKG_DIR" ] || [ ! -d "$MT76_PKG_DIR" ]; then
    echo "!!!! mt76 PACKAGE build dir is missing after the build."
    echo "     Expected: build_dir/target-*/linux-*/mt76-<version>/"
    echo "     kmod-mt7915e is built from this tree - without it the"
    echo "     firmware would ship with no MediaTek WiFi driver at all."
    echo "--- what exists under build_dir/target-*/linux-*/ ---"
    ls -d build_dir/target-*/linux-*/*/ 2>/dev/null | head -20
    exit 1
fi
MT76_MAC="$MT76_PKG_DIR/mac80211.c"
if [ ! -f "$MT76_MAC" ]; then
    echo "!!!! $MT76_MAC not found inside the mt76 package tree."
    ls -la "$MT76_PKG_DIR" 2>/dev/null | head -20
    exit 1
fi
# Count only real array entries - CHAN5G(36, 5180). A plain
# grep -c 'CHAN5G(' also counts the "#define CHAN5G(_idx, _freq)"
# macro and reports 69 for a 68-channel table, which is exactly the
# kind of off-by-one that turns a threshold check into a coin flip.
CHAN5G_COUNT=$(grep -cE 'CHAN5G\(-?[0-9]+, *[0-9]+\)' "$MT76_MAC" 2>/dev/null || true)
echo "mt76 package source : $MT76_MAC"
echo "CHAN5G entries      : $CHAN5G_COUNT  (stock 28, patched 68)"
if [ "${CHAN5G_COUNT:-0}" -lt 60 ]; then
    echo "!!!! The mt76 package still carries only $CHAN5G_COUNT CHAN5G entries,"
    echo "     so 999-mercury-superchannels.patch did NOT apply. The driver"
    echo "     would expose fewer channels than the regdb allows and every"
    echo "     extended channel would fail silently on the device."
    echo "--- patches present in the package ---"
    ls -l package/kernel/mt76/patches/ 2>/dev/null || echo "(no patches dir)"
    echo "--- first lines of our patch ---"
    head -12 package/kernel/mt76/patches/999-mercury-superchannels.patch 2>/dev/null
    exit 1
fi
echo "OK: mt76 package carries the extended $CHAN5G_COUNT-channel table."

# Prove the PATCHED source is what actually got compiled: a module must
# exist inside this same package tree. Counting channels in a source
# file that was never compiled would be a hollow check.
MT76_KO=$(find "$MT76_PKG_DIR" \( -name 'mt76.ko' -o -name 'mt7915e.ko' \) 2>/dev/null | head -n4)
if [ -z "$MT76_KO" ]; then
    echo "!!!! No mt76.ko / mt7915e.ko was built inside $MT76_PKG_DIR."
    echo "     The patched source exists but was never compiled into a"
    echo "     module, so the device would have no WiFi driver."
    exit 1
fi
echo "Built modules       :"
echo "$MT76_KO" | sed 's|^|  |'

# Report the kernel's unused in-tree copy explicitly so its stock 28
# channels are never again mistaken for a failure.
INTREE=$(ls build_dir/toolchain-*/linux-*/drivers/net/wireless/mediatek/mt76/mac80211.c 2>/dev/null | head -n1)
if [ -n "$INTREE" ]; then
    echo "(kernel in-tree mt76: $(grep -cE 'CHAN5G\(-?[0-9]+, *[0-9]+\)' "$INTREE") channels - unused by design, not built)"
fi

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
# Always show everything that was produced. Without this the log says
# nothing about which images exist, so a missing initramfs (or an image
# named differently than expected) can only be guessed at afterwards.
echo "--- all files in $BIN_DIR ---"
ls -la "$BIN_DIR" 2>/dev/null | sed 's/^/  /' || true

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

# Compare against the file Step 1 generated instead of against a guessed
# byte count. Both the wireless-regdb package and our files/ overlay
# install /lib/firmware/regulatory.db; if the package's stock database
# ever won that race a size threshold could still pass while every
# extended channel stayed locked. Identical checksums are the only proof
# that the unlocked database is the one actually shipping.
OURS="files/lib/firmware/regulatory.db"
if [ ! -f "$OURS" ]; then
    echo "!!!! $OURS missing - Step 1 did not stage the custom database."
    exit 1
fi
SUM_ROOTFS=$(md5sum "$REGDB" | awk '{print $1}')
SUM_OURS=$(md5sum "$OURS"   | awk '{print $1}')
echo "  rootfs copy : $REGDB ($REGDB_SZ bytes, md5 ${SUM_ROOTFS:0:12})"
echo "  generated   : $OURS ($(wc -c < "$OURS") bytes, md5 ${SUM_OURS:0:12})"
if [ "$SUM_ROOTFS" != "$SUM_OURS" ]; then
    echo "!!!! The regulatory.db in the rootfs is NOT the one we generated."
    echo "     The stock wireless-regdb database has overwritten ours, so the"
    echo "     68-channel driver table would be regulatory-blocked and every"
    echo "     extended channel would silently refuse to transmit."
    exit 1
fi
echo "  OK: unlocked regulatory.db is byte-identical in the rootfs."

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

# The bootloader on this board boots a FIT and verifies its crc32+sha1
# before jumping; a legacy uImage is rejected and the device simply does
# not come up. That is precisely what the ramips default KERNEL recipe
# ("uImage lzma") produced here until the device definition was given an
# explicit "fit lzma" KERNEL. Check the magic so the same class of defect
# can never ship silently again:
#   FIT / DTB magic = d0 0d fe ed
#   legacy uImage   = 27 05 19 56
KMAGIC=$(tar -xOf "$TAR_IMAGE" "$KERNEL_MEMBER" 2>/dev/null | od -An -tx1 -N4 | tr -d ' \n')
echo "  kernel magic: $KMAGIC"
case "$KMAGIC" in
    d00dfeed)
        echo "  OK: kernel is a FIT image (denx,fit) as the bootloader requires." ;;
    27051956)
        echo "!!!! kernel is a LEGACY uImage (magic 27051956), not a FIT."
        echo "     Both firmware banks are declared compatible = \"denx,fit\" in"
        echo "     the DTS and U-Boot verifies a FIT header, so this image would"
        echo "     flash successfully and then fail to boot."
        echo "     Fix: set KERNEL := kernel-bin | lzma | fit lzma ...dtb in the"
        echo "     device definition (scripts/mercury-02-patch-makefiles.sh)."
        exit 1 ;;
    *)
        echo "!!!! kernel has unrecognised magic '$KMAGIC' - expected d00dfeed (FIT)."
        exit 1 ;;
esac

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

# NOTE ON U-BOOT: this build cannot produce one. OpenWrt v24.10.2 has no
# U-Boot package for ramips/mt7621 at all (only uboot-mediatek, -mvebu,
# -ath79, ...), because MT7621 boards run the vendor bootloader. Earlier
# revisions of this script searched build_dir for a u-boot.bin that could
# never exist and then just warned, which read like "optional" when it is
# actually a hard prerequisite of the UART recovery path. The bootloader
# has to be dumped off the device instead - and the device's own copy is
# the only one guaranteed to match this board's DDR and NAND timings:
#     ssh/telnet to the box, then:  dd if=/dev/mtd0 of=/tmp/uboot_vendor.bin
echo "  u-boot: not buildable for mt7621 - dump /dev/mtd0 off the device"
echo "          (see HOW_TO_USE.txt; this is expected, not a failure)"

# The initramfs image IS buildable, and the whole first-install and
# brick-recovery story depends on it, so treat a missing one as a real
# defect rather than a warning.
INITRAMFS=$(find "$BIN_DIR" -type f -name "*mercury_km15-103h*initramfs*.itb" 2>/dev/null | head -n1)
[ -n "$INITRAMFS" ] || INITRAMFS=$(find "$BIN_DIR" -type f -name "*mercury_km15-103h*initramfs*" 2>/dev/null | head -n1)
if [ -n "$INITRAMFS" ]; then
    cp "$INITRAMFS" "$RECOVERY_DIR/$(basename "$INITRAMFS")"
    echo "  OK: initramfs image ($(wc -c < "$INITRAMFS") bytes)"
else
    echo "!!!! No *-initramfs-uImage.itb was produced."
    echo "     Without it there is no way to boot OpenWrt from RAM, which is"
    echo "     how this device is meant to be installed and rescued (its"
    echo "     U-Boot has no interactive console except the SPL Ymodem trap)."
    echo "--- images that WERE produced ---"
    ls -la "$BIN_DIR" 2>/dev/null | sed 's/^/     /'
    echo "--- initramfs-related settings ---"
    grep -E 'INITRAMFS' .config 2>/dev/null | sed 's/^/     /' || echo "     (no INITRAMFS symbol in .config)"
    grep -nE 'KERNEL_INITRAMFS|initramfs-kernel' target/linux/ramips/image/mt7621.mk 2>/dev/null |
        grep -A2 -B2 mercury | sed 's/^/     /' || true
    exit 1
fi

# Write the U-Boot boot commands to a README
cat > "$RECOVERY_DIR/HOW_TO_USE.txt" << 'HOWTO'
Mercury KM15-103H UART Recovery / First Install
===============================================

WHAT IS IN THIS ARCHIVE
  *-initramfs-uImage.itb   OpenWrt that runs entirely from RAM
  HOW_TO_USE.txt           this file
  (there is deliberately no u-boot.bin - see STEP 0)

STEP 0 - Get a u-boot.bin (ONE TIME, while the device still boots)
  OpenWrt cannot build U-Boot for MT7621; the vendor bootloader is the
  only compatible one. Dump it off the running device and keep it safe:
     dd if=/dev/mtd0 of=/tmp/uboot_vendor.bin      # "Bootloader" partition
  then copy it to your PC (scp, or tftp/wget from the box).
  Without this file the Ymodem step below has nothing to send.

STEP 1 - Get U-Boot running in RAM
  1. Connect UART (115200 8N1) + Tera Term
  2. Power on the device
  3. While SPL is still printing, short NAND pin 9 (#CE) to GND
     -> SPL fails to read the bootloader and falls back to Ymodem
  4. Wait for: "Accepted mode is Ymodem-1K."
  5. Tera Term: File > Transfer > YMODEM > Send -> uboot_vendor.bin
  6. U-Boot boots into RAM and gives you a "#" prompt

STEP 2 - Load OpenWrt initramfs into RAM
  At the U-Boot "#" prompt:
      loady 0x84000000
  Tera Term: File > Transfer > YMODEM > Send -> *-initramfs-uImage.itb
  Then:
      bootm 0x84000000
  OpenWrt now runs from RAM with NO NAND partition mounted.

STEP 3 - Flash to NAND permanently
  SSH into 192.168.1.1 (the initramfs default IP):
      scp *-sysupgrade.bin root@192.168.1.1:/tmp/
      ssh root@192.168.1.1 "sysupgrade -n /tmp/*-sysupgrade.bin"

STEP 4 (OPTIONAL) - wipe NAND before flashing
  From the initramfs shell, where nothing is mounted from NAND:
      cat /proc/mtd                 # confirm the numbers first!
      flash_erase /dev/mtdN 0 0     # Config / firmware / firmware2 / Userdata
  then do STEP 3.

  NEVER erase the Bootloader or Factory partitions:
  Bootloader = the only thing that can start the board at all.
  Factory    = WiFi EEPROM + calibration; erasing it kills the radio
               permanently and it cannot be regenerated.

AFTER FLASHING - confirm the build is complete
      mercury-wifi-check            # channels, 160 MHz, power, firmware blobs
      iw phy phy1 info | grep -A2 "160 MHz"
      grep -c processor /proc/cpuinfo    # expect 4
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
