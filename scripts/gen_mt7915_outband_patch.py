#!/usr/bin/env python3
"""
EXPERIMENTAL: feed the real centre frequency to the MT7915 MCU via the
undocumented `outband_freq` field, to try to beacon on non-standard 5 GHz
channels the MCU otherwise refuses ("Failed to set beacon parameters").

opt-in only - mercury-05-compile.sh runs it when MERCURY_ENABLE_OUTBAND is
set. Never in the stable build.

THE THEORY
----------
mt7915_mcu_set_chan_info() sends the MCU channel NUMBERS (control_ch,
center_ch) and the closed MCU firmware maps them to a frequency from its
own table, rejecting anything non-standard. The request struct also carries
two fields the mainline driver never populates:

    __le32 outband_freq;   /* raw centre frequency in MHz */
    u8     channel_band;

`outband_freq` staying 0 is why the MCU always falls back to its channel
table. This patch sets outband_freq to the real centre (chandef->
center_freq1) for 5 GHz, on the theory that a non-zero value makes the MCU
tune the RF directly and bypass the table.

HONEST UNCERTAINTY
------------------
Nothing in the open driver uses this field, so the exact trigger is
undocumented. Three outcomes are all possible:
  1. The MCU honours outband_freq -> non-standard channels beacon. Win.
  2. The MCU ignores it without the right channel_band value -> no change,
     and the next thing to try is a channel_band trigger from the MediaTek
     vendor SDK.
  3. The MCU chokes on the unexpected value -> MCU timeout / needs reboot.
Because (3) is real, this is flag-gated and must be tested on the bench,
not shipped. Try it on one channel and watch dmesg for "Message ... timeout".

Run from the openwrt/ directory after:
    make package/kernel/mt76/prepare

Output: package/kernel/mt76/patches/993-mt7915-outband-freq.patch
"""

import difflib
import os
import re
import sys

PKG_DIR = 'package/kernel/mt76'
PATCH_OUT = os.path.join(PKG_DIR, 'patches', '993-mt7915-outband-freq.patch')


def fail(msg):
    print('!!!! ' + msg)
    sys.exit(1)


def find_mcu_c(build_root):
    for dirpath, _dirs, files in os.walk(build_root):
        if 'mcu.c' not in files:
            continue
        norm = dirpath.replace('\\', '/')
        if '/target-' not in norm:
            continue
        if not norm.endswith('/mt7915') and '/mt7915/' not in norm:
            continue
        path = os.path.join(dirpath, 'mcu.c')
        try:
            with open(path, encoding='utf-8', errors='ignore') as fh:
                text = fh.read()
            if 'mt7915_mcu_set_chan_info' in text and 'outband_freq' in text:
                return path, text
        except OSError:
            continue
    return None, None


def patch_outband(text):
    is_crlf = '\r\n' in text
    t = text.replace('\r\n', '\n')

    # Insert right after the req initializer's closing "};" inside
    # mt7915_mcu_set_chan_info. Anchor on the .channel_band line that ends
    # the initializer, then the "\t};" that closes it.
    anchor = re.compile(
        r'(\.channel_band = ch_band\[chandef->chan->band\],\n\t\};\n)'
    )
    if not anchor.search(t):
        fail('req initializer end anchor not found - driver text changed.')

    inject = (
        r'\1\n'
        r'\t/* Mercury EXPERIMENTAL: hand the MCU the real centre frequency so\n'
        r'\t * it can tune non-standard 2.4/5 GHz centres its channel table refuses.\n'
        r'\t * Undocumented vendor field - test on the bench, watch for MCU timeouts. */\n'
        r'\treq.outband_freq = cpu_to_le32(freq1);\n'
    )
    t2, n = anchor.subn(inject, t, count=1)
    if n != 1:
        fail('expected exactly 1 injection, made %d' % n)

    if is_crlf:
        t2 = t2.replace('\n', '\r\n')
    return t2


def relative_path(mcu_c_path):
    norm = mcu_c_path.replace('\\', '/')
    parts = norm.split('/')
    for i in range(len(parts) - 1, 0, -1):
        if os.path.exists(os.path.join('/'.join(parts[:i]), 'mt76.h')):
            return '/'.join(parts[i:])
    return '/'.join(parts[-2:])


def main():
    build_root = sys.argv[1] if len(sys.argv) > 1 else 'build_dir'
    if not os.path.isdir(PKG_DIR):
        fail('%s not found. Run from the openwrt/ directory.' % PKG_DIR)

    print('Searching for mt7915/mcu.c under %s ...' % build_root)
    path, old_text = find_mcu_c(build_root)
    if path is None:
        fail("mt7915/mcu.c (with mt7915_mcu_set_chan_info and outband_freq) "
             "not found under %s." % build_root)
    print('  found: %s' % path)

    new_text = patch_outband(old_text)
    rel = relative_path(path)
    diff_lines = list(difflib.unified_diff(
        old_text.replace('\r\n', '\n').splitlines(keepends=True),
        new_text.replace('\r\n', '\n').splitlines(keepends=True),
        fromfile='a/' + rel, tofile='b/' + rel, n=3))

    os.makedirs(os.path.dirname(PATCH_OUT), exist_ok=True)
    with open(PATCH_OUT, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write('# Mercury KM15-103H: EXPERIMENTAL outband_freq for non-standard 5 GHz centres\n')
        fh.write('# Undocumented MCU field - bench test only, may time out the MCU.\n')
        fh.write('\n')
        fh.writelines(diff_lines)

    print('  wrote: %s  (%d diff lines)' % (PATCH_OUT, len(diff_lines)))


if __name__ == '__main__':
    main()
