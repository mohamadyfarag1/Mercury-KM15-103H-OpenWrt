#!/usr/bin/env python3
"""
Replace mt76_channels_5ghz[] with a 5 MHz-grid table, scoped to the bands
the regdb actually grants and the MT7915E calibration actually covers.

WHY THIS EXISTS
---------------
The user wants odd (5 MHz-grid) 5 GHz channels for point-to-point / client
links, the way Ubiquiti gear exposes them. The removed 177-channel table
(5100-6110 MHz) tried to do this but ran outside calibration and outside
the regulatory rules, so half of it was dead. This is the clean version:
the continuous 5 MHz grid, but ONLY inside the three sub-bands the custom
regdb grants (mercury-06), each trimmed so a channel's own 20 MHz fits the
rule (cfg80211 disables any channel whose edge leaves the rule - the exact
trap the old 5100 floor hit):

    band A  ch30-64   5150-5320   (regdb 5140-5330)
    band B  ch100-144 5500-5720   (regdb 5490-5730)
    band C  ch149-177 5745-5885   (regdb 5735-5895)

The DFS void 5330-5490 (ch66-96) is left out because the regdb does not
grant it - putting channels there would just make them appear disabled.
Every channel here is within calibration, so it radiates, AND it is in the
one table both AP and station/WDS mode read - so a second unit on this same
firmware sees these channels when it scans. There is no separate client
channel table.

Run from the openwrt/ directory after:
    make package/kernel/mt76/prepare

Output: package/kernel/mt76/patches/995-mt7915-5ghz-grid.patch
"""

import difflib
import os
import re
import sys

PKG_DIR = 'package/kernel/mt76'
PATCH_OUT = os.path.join(PKG_DIR, 'patches', '995-mt7915-5ghz-grid.patch')

# 5 GHz channel N sits at 5000 + N*5 MHz. Piecewise 5 MHz grid, each range
# trimmed so the channel's 20 MHz stays inside its regdb rule.
#
# With the outband experiment on (MERCURY_ENABLE_OUTBAND), band A reaches
# down to ch20 (5100 MHz) so the low channels the user wants exist in the
# table for the outband_freq patch to try to tune. These are far below
# calibration and only stand a chance via outband, so they are tied to that
# flag; the stable table still starts at ch30 (5150). The regdb low-rule
# floor in mercury-06 drops to 5090 under the same flag so ch20's 20 MHz
# (5090-5110) fits.
_ob = os.environ.get('MERCURY_ENABLE_OUTBAND', '').strip().lower()
LOW_START = 20 if _ob not in ('', '0', 'no', 'false', 'disable') else 30
CHANS_5G = (list(range(LOW_START, 65))  # 5100/5150-5320 (rule 5090/5140-5330)
            + list(range(100, 145))     # 5500-5720  (rule 5490-5730)
            + list(range(149, 178)))    # 5745-5885  (rule 5735-5895)


def freq_5g(ch):
    return 5000 + ch * 5


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
        if 'mt76_channels_5ghz' in text and 'mt76_channels_2ghz' in text:
            return path, text
    return None, None


def main():
    build_root = sys.argv[1] if len(sys.argv) > 1 else 'build_dir'

    if not os.path.isdir(PKG_DIR):
        fail('%s not found. Run from the openwrt/ directory.' % PKG_DIR)

    print('Searching for mt76/mac80211.c under %s ...' % build_root)
    path, old_text = find_mt76_mac80211(build_root)
    if path is None:
        fail("mt76/mac80211.c not found under %s.\n"
             "Run 'make package/kernel/mt76/prepare V=s' first." % build_root)
    print('  found: %s' % path)

    pkg_root = os.path.dirname(path)
    if not os.path.exists(os.path.join(pkg_root, 'mt76.h')):
        fail('%s is not the mt76 source root (no mt76.h beside mac80211.c).'
             % pkg_root)

    is_crlf = '\r\n' in old_text
    t = old_text.replace('\r\n', '\n')

    entries = '\n'.join('\tCHAN5G(%d, %d),' % (ch, freq_5g(ch))
                        for ch in CHANS_5G)
    replacement = ('static const struct ieee80211_channel '
                   'mt76_channels_5ghz[] = {\n%s\n};' % entries)
    pattern = re.compile(
        r'static\s+const\s+struct\s+ieee80211_channel\s+'
        r'mt76_channels_5ghz\s*\[\s*\]\s*=\s*\{.*?\};', re.DOTALL)
    new_text, n = pattern.subn(replacement, t)
    if n != 1:
        fail('matched mt76_channels_5ghz[] %d times, expected exactly 1' % n)

    got = len(re.findall(r'CHAN5G\(-?\d+, *\d+\)', new_text))
    if got != len(CHANS_5G):
        fail('after replace got %d CHAN5G entries, expected %d'
             % (got, len(CHANS_5G)))
    if new_text == t:
        fail('no change produced.')

    rel = os.path.basename(path)
    diff_lines = list(difflib.unified_diff(
        t.splitlines(keepends=True),
        new_text.splitlines(keepends=True),
        fromfile='a/' + rel, tofile='b/' + rel, n=3))
    if is_crlf:
        diff_lines = [ln.replace('\n', '\r\n') for ln in diff_lines]

    os.makedirs(os.path.dirname(PATCH_OUT), exist_ok=True)
    with open(PATCH_OUT, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write('# Mercury KM15-103H: 5 GHz 5 MHz-grid table within granted/calibrated bands\n')
        fh.write('# %d channels: 5150-5320, 5500-5720, 5745-5885 MHz\n' % len(CHANS_5G))
        fh.write('\n')
        fh.writelines(diff_lines)

    print('  wrote: %s  (%d diff lines, %d channels)'
          % (PATCH_OUT, len(diff_lines), len(CHANS_5G)))


if __name__ == '__main__':
    main()
