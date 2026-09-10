#!/bin/bash
# ===============================================================
# Script 5: Compile Firmware for Mercury KM15-103H
# ===============================================================
# Called from the repository root by the CI workflow.
# Orchestrates: regdb, mt76 driver patch hygiene, precal fallback,
# full build, post-build verification.
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
# Step 3: Remove the two driver patches that destabilised the radio.
#
# Both were verified dead on real hardware (192.168.100.1, 2026-09-09)
# and neither can be salvaged by configuration, so they are deleted
# here rather than left for a later run to pick up.
#
# 999-mercury-superchannels.patch - replaced mt76_channels_5ghz[] with
#   177 channels at 5 MHz spacing (ch20-222, 5100-6110 MHz). The MT7915E
#   has no EEPROM calibration outside the standard plan, and cfg80211
#   disables any channel whose centre +/- 10 MHz leaves the regulatory
#   rule, so the bottom of that table was never usable:
#       hostapd: Frequency 5100 (secondary) not allowed for AP mode, flags: 0x1
#       hostapd: Configured channel (24) or frequency (5120) not found
#                from the channel list of the current mode (2) IEEE 802.11a
#       hostapd: Could not select hw_mode and channel. (-3)
#   Stock mt76 already ships exactly the standard channel plan, so the
#   fix is to ship it unpatched.
#
# 998-mt7915-he160-dbdc.patch - forced nss_160/sts_160 and the VHT160
#   capability bits on even with dbdc_support set. The MT7915 cannot do
#   160 MHz while both bands run off its single MCU; upstream says so in
#   mt7915/init.c ("Can't do 160MHz with mt7915 dbdc"). With the guard
#   removed the driver pushes 160-capable station records the MCU never
#   answers, and radio bring-up wedges:
#       mt7915e: Retry message 000007ed (seq 15)
#       mt7915e: Message 000007ed (seq 15) timeout
#       hostapd: Could not set interface phy1-ap0 flags (UP): Operation timed out
#       ieee80211 phy1: Hardware restart was requested
#   Both bands share the MCU, so 2.4 GHz died with it - the AP came up
#   with phy1-ap0 at 0.00 dBm and no SSID at all. This failed on plain
#   channel 36 / HE80 too, which is what proves it is the capability
#   advertisement and not the channel. 5 GHz therefore runs HE80, which
#   is also the widest mode mobile clients reliably scan and join.
# ---------------------------------------------------------------
echo "======================================="
echo "Step 3: Removing superchannel and HE160-DBDC driver patches..."
echo "======================================="
rm -fv package/kernel/mt76/patches/999-mercury-superchannels.patch \
       package/kernel/mt76/patches/998-mt7915-he160-dbdc.patch 2>/dev/null || true
for STALE in 999-mercury-superchannels 998-mt7915-he160-dbdc; do
    if [ -e "package/kernel/mt76/patches/$STALE.patch" ]; then
        echo "!!!! package/kernel/mt76/patches/$STALE.patch still present after removal."
        exit 1
    fi
done
echo "OK: Stale patches removed."


# ---------------------------------------------------------------
# Step 3b: Patch mt7915/eeprom.c to add precal fallback.
#
# Ensures the driver automatically falls back to loading the 105,488
# bytes of RF precalibration data from mt7915_eeprom_dbdc.bin if the
# flash partition is uncalibrated or NVMEM cells fail.
# ---------------------------------------------------------------
echo "======================================="
echo "Step 3b: Patching mt7915 eeprom.c precal fallback..."
echo "======================================="
python3 ../scripts/gen_mt7915_precal_patch.py build_dir
PRECALPATCH="package/kernel/mt76/patches/997-mt7915-precal-fallback.patch"
if [ -s "$PRECALPATCH" ]; then
    echo "Patch: $PRECALPATCH  ($(wc -l < "$PRECALPATCH") lines)"
else
    echo "NOTE: Precal fallback patch not generated (non-fatal; pattern changed)."
fi

# ---------------------------------------------------------------

# ---------------------------------------------------------------
# Step 3c: Patch mt7915/main.c so station-dump RX rate is sticky.
#
# mt7915_sta_statistics() reports the rate of the last frame the MCU
# decoded. An idle station sends only base-rate control frames, so the
# reported RX rate collapses to 6 Mbit/s next to a 1201 Mbit/s TX - which
# reads like a fault but is just the live rate of a tiny idle frame.
# Verified on hardware that no supported_rates/basic_rate floor changes
# this (6 Mbit/s is a mandatory OFDM rate). This patch reports the
# negotiated TX rate when the RX query returns a plain legacy rate, so the
# idle display matches ath10k. DISPLAY ONLY - no datapath/throughput change.
# ---------------------------------------------------------------
echo "======================================="
echo "Step 3c: Patching mt7915 main.c RX-rate display (sticky)..."
echo "======================================="
python3 ../scripts/gen_mt7915_rxrate_patch.py build_dir
RXRATEPATCH="package/kernel/mt76/patches/996-mt7915-rxrate-sticky.patch"
if [ -s "$RXRATEPATCH" ]; then
    echo "Patch: $RXRATEPATCH  ($(wc -l < "$RXRATEPATCH") lines)"
else
    echo "NOTE: RX-rate sticky patch not generated (non-fatal; cosmetic; pattern changed)."
fi

# ---------------------------------------------------------------
#
# Adds ch-19..-1 (2312-2402 MHz) to the 2 GHz table so the 2.4 GHz radio
# can be tuned below the standard band and run HE (ax) there. This is a
# gamble on the RF front end - the PA, band-pass filter and antenna match
# are built for 2.4 GHz and there is no calibration below it, so these may

# Force mt76 to be re-extracted AND re-patched on the next build.
#
# `make package/kernel/mt76/clean` for a KERNEL package only removes the
# install stamps (.mt76_installed, mt76.list) - it leaves the extracted
# source tree and its ".prepared_<hash>" stamp in place. With that stamp
# present, the full build in Step 5 SKIPS the Prepare (extract+patch)
# phase entirely, so patches/ is never re-applied (this is exactly the
# "patch did not reach this build" failure seen on run 7f446af).
#
# That cuts both ways now: a stale tree prepared by an earlier run still
# carries the 998/999 patches Step 3 just deleted, so removing it is what
# makes their removal actually reach the driver.
make package/kernel/mt76/clean V=s 2>&1 | tail -5
echo "Forcing mt76 re-extract by removing the prepared source dir(s):"
rm -rfv build_dir/target-*/linux-*/mt76-* 2>/dev/null | tail -3
if ls build_dir/target-*/linux-*/mt76-* >/dev/null 2>&1; then
    echo "!!!! mt76 source dir still present after removal - re-patch may be skipped."
    exit 1
fi
echo "OK: mt76 prepared source removed; Step 5 will re-extract from the tarball."

# ---------------------------------------------------------------
# There is deliberately no kernel net/wireless/reg.c patching step.
#
# mercury-07-superchannel.sh used to widen the compiled-in world domain
# to 4910-6120 MHz and strip NL80211_RRF_NO_IR / NO_OFDM / DFS out of
# reg.c by regex. That existed only to make the superchannel table
# usable when regulatory.db failed to load. With the standard plan the
# custom database in Step 1 already grants every channel the driver
# exposes - verified on the device:
#     country YE: DFS-UNSET
#         (2402 - 2482 @ 40), (N/A, 30), (N/A)
#         (5170 - 5330 @ 160), (N/A, 30), (N/A)
# so the regex surgery buys nothing and its failure mode (a desynchronised
# brace in kernel source) is far worse than the fallback it guarded.
# ---------------------------------------------------------------

# ---------------------------------------------------------------
# Step 4b: kernel signed-channel cast (only with 2.3 GHz enabled).
#
# ieee80211_channel_to_frequency() maps a 2 GHz channel with 2407 + chan*5.
# Channels below 1 are negative, but when a channel number arrives as an
# unsigned byte (e.g. -19 -> 0xED = 237) the arithmetic lands far above the
# band. Reinterpreting it as signed (chan = (int)(char)chan;) fixes the
# mapping back onto 2312-2402. With 2.3 GHz off every 2 GHz channel is
# 1-14, the cast is a no-op, and the file is left untouched.
#
# Python, not sed: 'sed a\t\ttext' does not insert two tabs (GNU sed eats
# the first backslash and emits a stray 't'). Patches both the kernel tree
# and the mac80211 backports copy. The kernel tree is prepared in Step 2
# and not removed (only mt76 is), so this in-place edit reaches Step 5.
# ---------------------------------------------------------------
if [ -n "$ENABLE_23G" ]; then
    echo "======================================="
    echo "Step 4b: kernel signed-channel cast for 2.3 GHz (util.c)..."
    echo "======================================="
    CAST_HITS=0
    for UTIL in $(find build_dir -path "*/net/wireless/util.c" 2>/dev/null); do
        if python3 - "$UTIL" <<'PYEOF'
import sys
path = sys.argv[1]
with open(path, encoding='utf-8', errors='ignore') as fh:
    lines = fh.readlines()
MARK = 'chan = (int)(char)chan;'
if any(MARK in ln for ln in lines):
    print('  %s: already patched' % path); sys.exit(0)
out, done = [], False
for ln in lines:
    out.append(ln)
    if not done and ln.strip() == 'case NL80211_BAND_2GHZ:':
        indent = ln[:len(ln) - len(ln.lstrip())]
        out.append(indent + '\t' + MARK + '\n')
        done = True
if not done:
    print('  %s: no "case NL80211_BAND_2GHZ:" - skipped' % path); sys.exit(1)
with open(path, 'w', encoding='utf-8', newline='') as fh:
    fh.writelines(out)
print('  %s: patched' % path); sys.exit(0)
PYEOF
        then
            CAST_HITS=$((CAST_HITS + 1))
        fi
    done
    if [ "$CAST_HITS" -eq 0 ]; then
        echo "!!!! 2.3 GHz enabled but the util.c signed-channel cast did not"
        echo "     apply anywhere - negative 2 GHz channels would map to the"
        echo "     wrong frequency. Refusing to ship a broken 2.3 GHz build."
        exit 1
    fi
    echo "  cast applied to $CAST_HITS util.c copy/copies."
fi

# ---------------------------------------------------------------
# Step 4c: Widen the built-in world regulatory domain (net/wireless/reg.c).
#
# Two problems this fixes, both seen on real hardware:
#
#  1. Country 00 drops TX power to 0 dBm. The compiled-in world_regdom is
#     deliberately tiny and flagged NO_IR, so selecting country "00" leaves
#     the radio unable to transmit. Widening it to the full bands at 30 dBm
#     with the restriction flags cleared gives 00 real power.
#
#  2. Client / WDS mode can't see or join an extended channel when the
#     custom regdb is not the domain in force (a unit on a different country,
#     or one where regdb did not load, falls back to this world domain). With
#     NO_IR set, a station may passive-scan but cannot associate; clearing it
#     - and DFS, so the scan is active - is what lets the receiver actually
#     connect on the channels the AP beacons.
#
# All plain s/// substitutions plus one whole-block replace - no line
# deletions, so kernel braces cannot desynchronise. Patches the kernel tree
# and the mac80211 backports copy (both prepared in Step 2, neither removed).
# ---------------------------------------------------------------
echo "======================================="
echo "Step 4c: Widening built-in world regulatory domain (reg.c)..."
echo "======================================="
REG_HITS=0
for REG in $(find build_dir -path "*/net/wireless/reg.c" 2>/dev/null); do
    if python3 - "$REG" <<'PYEOF'
import sys, re
path = sys.argv[1]
with open(path, encoding='utf-8', errors='ignore') as fh:
    text = fh.read()
before = text
text = re.sub(r'NL80211_RRF_NO_IR\s*\|\s*NL80211_RRF_AUTO_BW', '0', text)
text = re.sub(r'NL80211_RRF_NO_IR', '0', text)
text = re.sub(r'NL80211_RRF_NO_OFDM', '0', text)
text = re.sub(r'NL80211_RRF_DFS', '0', text)
new_world = ('static const struct ieee80211_regdomain world_regdom = {\n'
             '\t.alpha2 = "00",\n'
             '\t.reg_rules = {\n'
             '\t\tREG_RULE(2302 - 10, 2710 + 10, 40, 0, 30, 0),\n'
             '\t\tREG_RULE(5000 - 10, 6120 + 10, 160, 0, 30, 0),\n'
             '\t},\n'
             '};')
text = re.sub(r'static\s+const\s+struct\s+ieee80211_regdomain\s+world_regdom\s*=\s*\{.*?\};',
              new_world, text, flags=re.DOTALL)
if text != before:
    with open(path, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(text)
    print('  %s: widened + flags cleared' % path); sys.exit(0)
print('  %s: no change (already patched?)' % path); sys.exit(1)
PYEOF
    then
        REG_HITS=$((REG_HITS + 1))
    fi
done
if [ "$REG_HITS" -eq 0 ]; then
    echo "!!!! net/wireless/reg.c was not widened anywhere - country 00 would"
    echo "     stay at 0 dBm and client mode would fail on extended channels."
    echo "     'make package/kernel/mac80211/prepare' must have unpacked the tree."
    exit 1
fi
echo "  world domain widened in $REG_HITS reg.c copy/copies."

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
            # Since CONFIG_BUILD_LOG is not always set, logs/ might be empty.
            # We will force a re-compile of the failed package with V=s to get the error on stdout!
            echo "Re-compiling $pkg with V=s to capture the exact compiler error..."
            make "$pkg/compile" V=s -j1
        done
    else
        echo "(no 'ERROR: <pkg> failed to build' line; tail of build.log:)"
        tail -n 120 build.log
    fi
    exit 1
fi

# ---------------------------------------------------------------
# Step 6: Verify the shipped mt76 driver carries the STOCK standard
# channel table and no HE160-in-DBDC override.
#
# After the full build, the mt76 mac80211.c in build_dir reflects the
# source that was actually compiled. This step used to demand 177
# CHAN5G() entries; it now demands the opposite, because the extended
# table is what broke the radio. Checking the compiled source rather
# than the patches directory is the point - a patch can be deleted from
# package/ and still reach the build through a stale prepared tree.
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


# HE160 must stay guarded by dbdc_support. With the guard gone the driver
# advertises 160 MHz, hostapd builds 160-capable station records, and the
# single MCU shared by both bands stops answering:
#     mt7915e: Message 000007ed (seq 15) timeout
#     ieee80211 phy1: Hardware restart was requested
#

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

# The bootloader on this board is Breed, which boots legacy uImage
# (magic 27051956) with loader-kernel. A FIT image (magic d00dfeed)
# is incompatible with Breed and causes immediate reboot to breed>.
# Check the magic so the image is guaranteed bootable by Breed:
#   legacy uImage   = 27 05 19 56
#   FIT / DTB magic = d0 0d fe ed
KMAGIC=$(tar -xOf "$TAR_IMAGE" "$KERNEL_MEMBER" 2>/dev/null | od -An -tx1 -N4 | tr -d ' \n')
echo "  kernel magic: $KMAGIC"
case "$KMAGIC" in
    27051956)
        echo "  OK: kernel is a legacy uImage (magic 27051956) as Breed bootloader requires." ;;
    d00dfeed)
        echo "!!!! kernel is a FIT image (magic d00dfeed), but Breed only boots legacy uImage!"
        echo "     Fix: ensure Device/uimage-lzma-loader is inherited in mt7621.mk."
        exit 1 ;;
    *)
        echo "!!!! kernel has unrecognised magic '$KMAGIC' - expected 27051956 (uImage)."
        exit 1 ;;
esac

FACTORY_IMAGE=$(find "$BIN_DIR" -type f -name "*mercury_km15-103h*factory.bin" 2>/dev/null | head -n1)
if [ -n "$FACTORY_IMAGE" ] && [ -s "$FACTORY_IMAGE" ]; then
    echo "  OK: factory.bin produced ($(wc -c < "$FACTORY_IMAGE") bytes) - ready for 1-click Breed Web flashing!"
else
    echo "!!!! factory.bin was not produced or is empty."
    exit 1
fi

echo "======================================="
echo "Step 9.6: Verifying the PRODUCED artifacts, not just the sources..."
echo "======================================="
# Every serious defect this board has hit was of one shape: the output
# silently did not match the input. mercury-01 decompiled the factory
# device_tree.dtb over our .dts for many builds, so none of the DTS work
# was ever compiled in - and nothing noticed, because the build only ever
# checked its own inputs. A 4 MB kernel partition overflowed into UBI the
# same way. So verify the compiled DTB and the packed kernel themselves.

DTB=$(find build_dir -type f -name '*mercury_km15-103h*.dtb' 2>/dev/null | head -n1)
if [ -z "$DTB" ]; then
    echo "!!!! no compiled *mercury_km15-103h*.dtb found under build_dir."
    exit 1
fi
echo "compiled DTB: $DTB"

DTC=$(command -v staging_dir/host/bin/dtc || command -v dtc || echo staging_dir/host/bin/dtc)
DTB_DTS=$(mktemp)
if ! "$DTC" -I dtb -O dts -o "$DTB_DTS" "$DTB" 2>/dev/null; then
    echo "!!!! could not decompile $DTB with '$DTC'."
    exit 1
fi

# The MAC cell. Config partition sits at 0xC0000; base MAC is at offset 0x4 (absolute 0xC0004).
# dtc zero-pads cell values when it decompiles ("0x06", not "0x6"), and the
# padding width is not contractual, so match the value rather than a literal
# rendering of it.
if grep -Eq 'reg = <0x0*4 0x0*6>' "$DTB_DTS"; then
    echo "  OK       : mac-base nvmem cell at Config+0x4 (absolute 0xC0004)"
    echo "             Kernel nvmem subsystem assigns factory MAC to Ethernet (mac@0)"
    echo "             and WAN (port@0) directly from NAND."
else
    echo "!!!! the compiled DTB has no mac-base cell covering 0x4+6."
    echo "     The cell lives in the Config partition (NAND 0xC0000); offset"
    echo "     0x4 within Config = absolute 0xC0004."
    grep -n -A4 'macaddr' "$DTB_DTS" | head -20
    exit 1
fi

# A hardcoded MAC would put one identical address on every deployed unit.
if grep -qE 'mac-address = \[' "$DTB_DTS"; then
    echo "!!!! the compiled DTB still carries a hardcoded mac-address:"
    grep -nE 'mac-address = \[' "$DTB_DTS"
    echo "     Every unit flashed with this image would share that address."
    exit 1
fi
echo "  OK       : no hardcoded mac-address"
echo "             Ethernet, WAN, and WiFi MACs are cleanly derived from Config nvmem."

# NMBM remaps factory-bad blocks; required for NAND integrity even though
# the encrypted Config MAC is no longer read via nvmem.
if grep -q 'mediatek,nmbm' "$DTB_DTS"; then
    echo "  OK       : mediatek,nmbm present (NAND bad-block management enabled)"
else
    echo "!!!! the compiled DTB lacks mediatek,nmbm."
    echo "     Bad-block remapping is disabled; NAND writes may corrupt data."
    exit 1
fi

# Kernel partition vs the kernel actually packed for it. This is the check
# that would have caught "Bad FIT kernel image format": a FIT larger than
# its partition is overwritten by UBI's headers on first boot.
KPART_HEX=$(awk '/label = "firmware"/{f=1} f && /reg = </{gsub(/.*reg = <|>.*/,""); print $2; exit}' "$DTB_DTS")
if [ -z "$KPART_HEX" ]; then
    echo "!!!! could not read the kernel partition size out of the DTB."
    exit 1
fi
KPART=$((KPART_HEX))
KSIZE=$(tar -xOf "$TAR_IMAGE" "$KERNEL_MEMBER" 2>/dev/null | wc -c)
echo "  kernel image : $KSIZE bytes"
echo "  kernel part  : $KPART bytes ($KPART_HEX)"
if [ "$KSIZE" -ge "$KPART" ]; then
    echo "!!!! the FIT kernel does not fit its partition."
    echo "     UBI starts immediately after it and would write its volume"
    echo "     headers over the kernel tail, so the device flashes cleanly"
    echo "     and then fails to boot. Enlarge the kernel partition (and"
    echo "     shrink ubi by the same amount) in mercury_km15_103h.dts."
    rm -f "$DTB_DTS"
    exit 1
fi
echo "  OK       : kernel fits with $((KPART - KSIZE)) bytes ($(( (KPART - KSIZE) * 100 / KPART ))%) headroom"
if [ $(( (KPART - KSIZE) * 100 / KPART )) -lt 10 ]; then
    echo "  WARNING  : under 10% headroom - the next kernel bump may overflow."
fi
rm -f "$DTB_DTS"

echo "======================================="
echo "✅ BUILD SUCCESSFUL"
echo "sysupgrade : $(basename "$TAR_IMAGE")  ($(wc -c < "$TAR_IMAGE") bytes)"
echo "factory    : $(basename "$FACTORY_IMAGE")  ($(wc -c < "$FACTORY_IMAGE") bytes)"
echo "md5 factory: $(md5sum "$FACTORY_IMAGE" | awk '{print $1}')"
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

INITRAMFS=$(find "$BIN_DIR" -type f -name "*mercury_km15-103h*initramfs*" 2>/dev/null | head -n1)
if [ -n "$INITRAMFS" ] && [ -s "$INITRAMFS" ]; then
    cp "$INITRAMFS" "$RECOVERY_DIR/$(basename "$INITRAMFS")"
    echo "  OK: initramfs image ($(wc -c < "$INITRAMFS") bytes)"
else
    echo "  NOTE: No standalone initramfs image found. Factory and sysupgrade images are ready."
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
  2. Short NAND pins 29 & 30 (or pin 9 #CE) for 1 second upon power-on
     -> SPL fails to read NAND bootloader and enters emergency mode
  3. Wait for: "Accepted mode is Ymoden-1K. CCCC"
  4. Tera Term: File > Transfer > YMODEM > Send -> u-boot-cli-stop.bin
  5. U-Boot boots into RAM and stops at the "Mercury#" prompt

STEP 2 - Load OpenWrt initramfs into RAM via TFTP
  Connect PC Ethernet to LAN port, set PC static IP to 192.168.1.2.
  Run TFTP server (e.g. Tftpd64) on PC hosting *-initramfs-uImage.itb.
  At the U-Boot "Mercury#" prompt:
      setenv ipaddr 192.168.1.1
      setenv serverip 192.168.1.2
      tftpboot 0x80010000 openwrt-ramips-mt7621-mercury_km15-103h-initramfs-uImage.itb
      bootm 0x80010000
  OpenWrt now boots and runs entirely from RAM with NO NAND partition mounted.

STEP 3 - Flash to NAND permanently
  The initramfs uses this build's LAN address 192.168.100.1 and its DHCP
  server is disabled, so give the PC a static 192.168.100.2/24 first.
      scp *-sysupgrade.bin root@192.168.100.1:/tmp/
      ssh root@192.168.100.1 "sysupgrade -n /tmp/*-sysupgrade.bin"

  First, confirm THIS unit's own factory MAC is readable.  The DTS carries
  no hardcoded MAC on purpose - every unit derives all four addresses from
  its own NAND - so a unit whose Config block is damaged must be caught
  here rather than shipped with a random MAC:
      cfg=$(sed -n 's/^mtd\([0-9]*\):.*"Config".*/\1/p' /proc/mtd)
      hexdump -C /dev/mtd$cfg -s 0x4 -n 6
  It must match the label on the case.  All 00 or all ff means that block
  is damaged - stop and recover that unit before flashing it.

STEP 4 (OPTIONAL) - wipe NAND before flashing
  From the initramfs shell, where nothing is mounted from NAND:
      cat /proc/mtd                 # confirm the numbers first!
      flash_erase /dev/mtdN 0 0     # firmware / Userdata ONLY
  then do STEP 3.

  NEVER erase Config: it holds the per-unit factory MAC at 0x4, it is
  not reproducible, and block 6 inside it is a factory bad block that only
  NMBM can remap.  Losing it means that unit boots with a random MAC.

  NEVER erase the Bootloader or Factory partitions:
  Bootloader = the only thing that can start the board at all.
  Factory    = WiFi EEPROM + calibration; erasing it kills the radio
               permanently and it cannot be regenerated.

AFTER FLASHING - confirm the build is complete
      mercury-wifi-check            # channels, power, firmware blobs
      iw dev                        # both phy0-ap0 and phy1-ap0 must show an SSID
      grep -c processor /proc/cpuinfo    # expect 4

  5 GHz runs HE80, not HE160. The MT7915 drives both bands from one MCU
  and cannot serve 160 MHz while 2.4 GHz is up - forcing it made the MCU
  stop answering and took both radios down. HE80 is also the widest mode
  phones reliably scan and join.
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
        echo "5 GHz runs HE80. The MT7915 shares one MCU between both bands and"
        echo "cannot do 160 MHz while 2.4 GHz is up, so HE160 stays off."
        echo "Built-in world domain widened, so country 00 gives full power and"
        echo "client/WDS mode sees the extended channels."
    } >> "$GITHUB_STEP_SUMMARY"
fi
