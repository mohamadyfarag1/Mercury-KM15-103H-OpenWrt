#!/usr/bin/env python3
"""
EXPERIMENTAL: add 2.3 GHz channels (2312-2402 MHz) to mt76_channels_2ghz[].

This is opt-in - mercury-05-compile.sh only runs it when MERCURY_ENABLE_23GHZ
is set. It is NOT part of the stable default build.

WHAT IT DOES
------------
Prepends channels -19..-1 to mt76_channels_2ghz[]:

    ch-19 2312, ch-18 2317, ... ch-1 2402   (5 MHz grid, 19 channels)

2 GHz channel N sits at 2407 + N*5, so sub-2.4 GHz channels carry NEGATIVE
numbers. The kernel's ieee80211_channel_to_frequency() needs the companion
signed-char cast (added in mercury-05 Step 4b) or a channel that arrives as
an unsigned byte maps to the wrong frequency. hostapd needs the 2312-2407
freq->channel mapping (added to its patch in mercury-04) to accept the band
in AP mode. The regdb (mercury-06) must grant down to 2302 so ch-19's
20 MHz fits.

THE HARDWARE CAVEAT (read before trusting any of this)
------------------------------------------------------
Putting the channels in the table makes them appear in `iw phy info`. It
does NOT make the radio RADIATE there. The MT7915E PA, the RF band-pass
filter and the antenna match are all built for 2.400-2.4835 GHz, the EEPROM
carries no calibration below 2.4 GHz, and the MCU may reject an out-of-band
channel switch outright. Every one of these channels MUST be measured on
the device (mercury-wifi-check flags 0 dBm; confirm a client can actually
associate and pass traffic) before it is trusted. Expect heavy attenuation.

Run from the openwrt/ directory after:
    make package/kernel/mt76/prepare

Output: package/kernel/mt76/patches/994-mt7915-23ghz.patch
"""

import difflib
import os
import re
import sys

PKG_DIR = 'package/kernel/mt76'
PATCH_OUT = os.path.join(PKG_DIR, 'patches', '994-mt7915-23ghz.patch')

# 2 GHz channel N -> 2407 + N*5 MHz. -19..-1 = 2312..2402.
CHANS_23G = list(range(-19, 0))


def freq_2g(ch):
    return 2407 + ch * 5


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
        if 'mt76_channels_2ghz' in text and 'CHAN2G(1, 2412)' in text:
            return path, text
    return None, None


def main():
    build_root = sys.argv[1] if len(sys.argv) > 1 else 'build_dir'

    if not os.path.isdir(PKG_DIR):
        fail('%s not found. Run from the openwrt/ directory.' % PKG_DIR)

    print('Searching for mt76/mac80211.c under %s ...' % build_root)
    path, old_text = find_mt76_mac80211(build_root)
    if path is None:
        fail("mt76/mac80211.c (with mt76_channels_2ghz and CHAN2G(1, 2412)) "
             "not found under %s.\nRun 'make package/kernel/mt76/prepare V=s' "
             "first." % build_root)
    print('  found: %s' % path)

    pkg_root = os.path.dirname(path)
    if not os.path.exists(os.path.join(pkg_root, 'mt76.h')):
        fail('%s is not the mt76 source root (no mt76.h beside mac80211.c).'
             % pkg_root)

    is_crlf = '\r\n' in old_text
    t = old_text.replace('\r\n', '\n')

    anchor = re.compile(r'(\n)(\t)(CHAN2G\(1, 2412\),)')
    if not anchor.search(t):
        fail('anchor "CHAN2G(1, 2412)," not found - table format changed.')

    new_lines = ''.join('\t%s\n' % ('CHAN2G(%d, %d),' % (ch, freq_2g(ch)))
                        for ch in CHANS_23G)
    new_text = anchor.sub(r'\1' + new_lines + r'\2\3', t, count=1)

    if new_text == t:
        fail('no change produced - refusing to write an empty patch.')

    for ch in CHANS_23G:
        if new_text.count('CHAN2G(%d, %d)' % (ch, freq_2g(ch))) != 1:
            fail('CHAN2G(%d, %d) not inserted cleanly.' % (ch, freq_2g(ch)))

    rel = os.path.basename(path)
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
        fh.write('# Mercury KM15-103H: EXPERIMENTAL 2.3 GHz channels 2312-2402 MHz\n')
        fh.write('# ch-19..-1 on the 5 MHz grid. Uncalibrated - measure on hardware.\n')
        fh.write('\n')
        fh.writelines(diff_lines)

    print('  wrote: %s  (%d diff lines, %d channels, %d-%d MHz)'
          % (PATCH_OUT, len(diff_lines), len(CHANS_23G),
             freq_2g(CHANS_23G[0]), freq_2g(CHANS_23G[-1])))


if __name__ == '__main__':
    main()
