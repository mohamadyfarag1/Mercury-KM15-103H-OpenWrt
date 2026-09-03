#!/usr/bin/env python3
"""
Generate a patch for mt76/mac80211.c that extends mt76_channels_5ghz[]
from the stock ~28-channel 20 MHz-spaced table to a 68-channel
10 MHz-spaced superchannel table covering 5180-5885 MHz.

WHY THIS EXISTS
--------------
The stock mt76_channels_5ghz[] carries only the standard regulatory
channels (36, 40, 44, 48 ... 177).  LuCI enumerates what the driver
registered, so it can only offer those channels.  This patch adds the
10 MHz-spaced intermediate channels (38, 42, 46 ...) so the full
superchannel plan is exposed.

Unlike ath10k, mt76 has NO build variants and NO compile-time size
constant (ARRAY_SIZE() is used directly), so:
  - there is no ATH10K_NUM_CHANS-style constant to update;
  - there is no wmi.h scan buffer to extend (mt76 uses software scan);
  - a single patch file in package/kernel/mt76/patches/ covers ALL
    builds without the variant-directory problem that forced
    gen_package_patches.py in the Horus project.

Run from the openwrt/ directory after:
    make package/kernel/mt76/prepare

Writes the patch to package/kernel/mt76/patches/999-mercury-superchannels.patch
and saves the frequency list to tmp/mercury-driver-freqs.txt for the
build-time drift check in mercury-05-compile.sh.
"""

import difflib
import os
import re
import sys

# Same channel plan as Horus/ath10k.  5 GHz channels are numbered at
# 5 MHz steps from 5000 MHz: channel N => 5000 + N*5 MHz.
#
# range(36, 147, 2): 36, 38, 40 ... 146  (56 channels, UNII-1 to UNII-2e)
# range(149, 166, 2): 149, 151 ... 165    (9 channels, UNII-3)
# [169, 173, 177]                          (3 channels, UNII-4 / extended)
# Total: 68 channels
CHANS = list(range(36, 147, 2)) + list(range(149, 166, 2)) + [169, 173, 177]


def chan_freq(ch):
    return 5000 + ch * 5


def fail(msg):
    print("!!!! " + msg)
    sys.exit(1)


def find_mt76_mac80211(build_root):
    """
    Return (path, text) for the mt76-specific mac80211.c that defines
    mt76_channels_5ghz[].  There is also a mac80211.c inside the
    backports tree - we exclude that one by requiring both
    mt76_channels_5ghz AND mt76_channels_2ghz in the same file.
    """
    for dirpath, _dirs, files in os.walk(build_root):
        if 'mac80211.c' not in files:
            continue
        path = os.path.join(dirpath, 'mac80211.c')
        try:
            with open(path, encoding='utf-8', errors='ignore') as fh:
                text = fh.read()
        except OSError:
            continue
        if 'mt76_channels_5ghz' in text and 'mt76_channels_2ghz' in text:
            return path, text
    return None, None


def build_new_table(old_text):
    """
    Replace the mt76_channels_5ghz[] array body with the extended list.
    Preserves the macro name and surrounding code unchanged.
    """
    new_entries = '\n'.join(
        '\tCHAN5G(%d, %d),' % (ch, chan_freq(ch))
        for ch in CHANS
    )
    new_array = (
        'static const struct ieee80211_channel mt76_channels_5ghz[] = {\n'
        + new_entries + '\n'
        + '};'
    )
    # Match the full array including its closing brace.
    # DOTALL so the pattern crosses newlines; non-greedy so it stops
    # at the FIRST };  (there is only one mt76_channels_5ghz).
    pattern = (
        r'static const struct ieee80211_channel mt76_channels_5ghz\[\] = \{'
        r'.*?'
        r'\};'
    )
    new_text, n = re.subn(pattern, new_array, old_text, flags=re.DOTALL)
    if n != 1:
        fail("Found %d match(es) for mt76_channels_5ghz[] - expected exactly 1" % n)
    return new_text


def main():
    build_root = sys.argv[1] if len(sys.argv) > 1 else 'build_dir'
    pkg_dir = 'package/kernel/mt76'

    print("Searching for mt76/mac80211.c in %s ..." % build_root)
    path, old_text = find_mt76_mac80211(build_root)
    if path is None:
        fail(
            "mt76/mac80211.c (with mt76_channels_5ghz) not found under %s.\n"
            "     Run 'make package/kernel/mt76/prepare V=s' first." % build_root
        )

    print("  Found   : %s" % path)
    existing = old_text.count('CHAN5G(')
    print("  Stock   : %d CHAN5G entries" % existing)
    print("  Target  : %d CHAN5G entries" % len(CHANS))

    new_text = build_new_table(old_text)
    new_count = new_text.count('CHAN5G(')
    if new_count != len(CHANS):
        fail("After substitution got %d CHAN5G entries, expected %d" % (new_count, len(CHANS)))

    # Unified diff relative to the build root so the patch header
    # matches what 'patch -p1' expects when applied from openwrt/.
    rel = os.path.relpath(path, '.')
    diff_lines = list(difflib.unified_diff(
        old_text.splitlines(keepends=True),
        new_text.splitlines(keepends=True),
        fromfile='a/' + rel,
        tofile='b/' + rel,
        n=3,
    ))
    if not diff_lines:
        print("  No diff produced - channel table already at %d entries." % len(CHANS))
        return

    patch_path = os.path.join(pkg_dir, 'patches', '999-mercury-superchannels.patch')
    os.makedirs(os.path.dirname(patch_path), exist_ok=True)
    with open(patch_path, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(
            "# Mercury KM15-103H: extend mt76_channels_5ghz[] to %d-channel superchannel table\n"
            "# 10 MHz spacing, %d-%d MHz - same plan as Horus (ath10k build)\n\n"
            % (len(CHANS), chan_freq(CHANS[0]), chan_freq(CHANS[-1]))
        )
        fh.writelines(diff_lines)
    print("  Wrote   : %s  (%d lines)" % (patch_path, len(diff_lines)))

    # Write freq list for the build-time drift check in mercury-05-compile.sh
    os.makedirs('tmp', exist_ok=True)
    with open('tmp/mercury-driver-freqs.txt', 'w') as fh:
        for ch in CHANS:
            fh.write('%d\n' % chan_freq(ch))
    print("  Freqs   : tmp/mercury-driver-freqs.txt  (%d channels, %d-%d MHz)" % (
        len(CHANS), chan_freq(CHANS[0]), chan_freq(CHANS[-1])))


if __name__ == '__main__':
    main()
