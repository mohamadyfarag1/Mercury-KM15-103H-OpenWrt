#!/usr/bin/env python3
"""
Conservatively extend mt76_channels_5ghz[] DOWNWARD into the lower UNII-1
edge (5150-5170 MHz), and nothing else.

BACKGROUND
----------
An earlier build replaced the whole 5 GHz table with 177 channels at 5 MHz
spacing (5100-6110 MHz). Most of them were outside the MT7915E's EEPROM
calibration and either refused to beacon or came up at the wrong power, so
that approach was removed and the driver went back to the stock standard
table (ch36-177, 5170-5885). See mercury-05-compile.sh Step 3.

This adds back ONLY the handful of channels immediately below the standard
floor, on the 5 MHz grid:

    ch30 5150, ch31 5155, ch32 5160, ch33 5165, ch34 5170

These sit right at the bottom edge of the MT7915E's 5 GHz calibration
(which begins around 5150 MHz), so they are the extended channels most
likely to actually radiate. Everything below 5150 is left out - it needs
the on-device channel sweep, not a guess.

The companion regdb rule (mercury-06-generate-regdb.sh) must reach down to
5140 so ch30's 20 MHz (5140-5160) fits: cfg80211 disables any channel whose
edges leave the rule, which is exactly what silently killed the bottom of
the old superchannel table. Stock hostapd already maps 5000-5900 MHz via
(freq-5000)/5, so no hostapd patch is needed for this range.

After flashing, run mercury-wifi-check: any of these that comes up at
0.0 dBm is past this board's calibration edge and should be dropped.

Run from the openwrt/ directory after:
    make package/kernel/mt76/prepare

Output: package/kernel/mt76/patches/995-mt7915-lowchan.patch
"""

import difflib
import os
import re
import sys

PKG_DIR = 'package/kernel/mt76'
PATCH_OUT = os.path.join(PKG_DIR, 'patches', '995-mt7915-lowchan.patch')

# (channel index, centre freq MHz), 5 MHz grid, 5150-5170.
LOW_CHANS = [(30, 5150), (31, 5155), (32, 5160), (33, 5165), (34, 5170)]


def fail(msg):
    print('!!!! ' + msg)
    sys.exit(1)


def find_mt76_mac80211(build_root):
    for dirpath, _dirs, files in os.walk(build_root):
        if 'mac80211.c' not in files:
            continue
        norm = dirpath.replace('\\', '/')
        if '/target-' not in norm:
            continue
        path = os.path.join(dirpath, 'mac80211.c')
        try:
            with open(path, encoding='utf-8', errors='ignore') as fh:
                text = fh.read()
        except OSError:
            continue
        if 'mt76_channels_5ghz' in text and 'CHAN5G(36, 5180)' in text:
            return path, text
    return None, None


def relative_path(mac_c_path):
    return os.path.basename(mac_c_path)


def main():
    build_root = sys.argv[1] if len(sys.argv) > 1 else 'build_dir'

    if not os.path.isdir(PKG_DIR):
        fail('%s not found. Run from the openwrt/ directory.' % PKG_DIR)

    print('Searching for mt76/mac80211.c under %s ...' % build_root)
    path, old_text = find_mt76_mac80211(build_root)
    if path is None:
        fail("mt76/mac80211.c (with mt76_channels_5ghz and CHAN5G(36, 5180)) "
             "not found under %s.\nRun 'make package/kernel/mt76/prepare V=s' "
             "first." % build_root)
    print('  found: %s' % path)

    pkg_root = os.path.dirname(path)
    if not os.path.exists(os.path.join(pkg_root, 'mt76.h')):
        fail('%s is not the mt76 source root (no mt76.h beside mac80211.c).'
             % pkg_root)

    # Insert the low channels immediately before the first ch36 entry, using
    # the same one-tab indentation the array already uses.
    is_crlf = '\r\n' in old_text
    t = old_text.replace('\r\n', '\n')

    anchor = re.compile(r'(\n)(\t)(CHAN5G\(36, 5180\),)')
    if not anchor.search(t):
        fail('anchor "CHAN5G(36, 5180)," not found - table format changed.')

    new_lines = ''.join('\t%s\n' % ('CHAN5G(%d, %d),' % (idx, freq))
                        for idx, freq in LOW_CHANS)
    new_text = anchor.sub(r'\1' + new_lines + r'\2\3', t, count=1)

    if new_text == t:
        fail('no change produced - refusing to write an empty patch.')

    # Sanity: every low channel must now be present exactly once.
    for idx, freq in LOW_CHANS:
        if new_text.count('CHAN5G(%d, %d)' % (idx, freq)) != 1:
            fail('CHAN5G(%d, %d) not inserted cleanly.' % (idx, freq))

    rel = relative_path(path)
    diff_lines = list(difflib.unified_diff(
        t.splitlines(keepends=True),
        new_text.splitlines(keepends=True),
        fromfile='a/' + rel,
        tofile='b/' + rel,
        n=3,
    ))
    if is_crlf:
        diff_lines = [ln.replace('\n', '\r\n') for ln in diff_lines]

    os.makedirs(os.path.dirname(PATCH_OUT), exist_ok=True)
    with open(PATCH_OUT, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write('# Mercury KM15-103H: add lower UNII-1 edge channels 5150-5170 MHz\n')
        fh.write('# ch30-34 on the 5 MHz grid - the calibrated edge below the standard floor\n')
        fh.write('\n')
        fh.writelines(diff_lines)

    print('  wrote: %s  (%d diff lines, %d channels)'
          % (PATCH_OUT, len(diff_lines), len(LOW_CHANS)))


if __name__ == '__main__':
    main()
