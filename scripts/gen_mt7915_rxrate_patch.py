#!/usr/bin/env python3
"""
Make mt7915 report a "sticky" RX rate in station dump, the way ath10k does.

THE PROBLEM
-----------
mt7915_sta_statistics() fills sinfo->rxrate from mt7915_mcu_get_rx_rate(),
which returns the rate of the LAST frame the MCU decoded from the station.
When the station is idle it only sends base-rate control frames (ACK,
QoS-null, block-ack), so the query collapses to 6 Mbit/s and LuCI shows
"RX 6 Mbit/s" next to a "TX 1201 Mbit/s" download. Verified on real
hardware (192.168.100.1, 2026-09-09): the number briefly rises to a real
HE rate during an active transfer and drops straight back to 6 the moment
the station goes quiet. 6 Mbit/s is a mandatory OFDM rate, so no AP-side
supported_rates / basic_rate change can raise it - tested, it does not.

An Atheros/ath10k AP on the same bench shows RX 144 Mbit/s while idle
because ath10k reports the last NEGOTIATED rate, not the last frame's
rate. This patch gives mt7915 the same behaviour.

WHAT IT CHANGES
---------------
In mt7915_sta_statistics(), when the queried RX rate is a plain legacy
rate (flags == 0, i.e. the idle base-rate case) it substitutes the
negotiated TX rate (msta->wcid.rate, already read into `txrate` a few
lines above) as the reported RX rate. During a real transfer the query
returns an HT/VHT/HE rate (flags != 0) and is reported unchanged.

This is a DISPLAY change only. It does not touch the datapath, the rate
control, or throughput - it changes what iw/LuCI print for an idle
station, nothing else.

WHY A GENERATED PATCH
---------------------
Same reason as the precal fallback: an in-place edit is undone the next
time OpenWrt runs Build/Prepare. Writing a real patch into
package/kernel/mt76/patches/ makes OpenWrt apply it on every unpack.

A no-match is NON-FATAL (sys.exit(0) with a warning): this is cosmetic,
so a driver version whose text moved should not fail the whole build.

Run from the openwrt/ directory after:
    make package/kernel/mt76/prepare

Output: package/kernel/mt76/patches/996-mt7915-rxrate-sticky.patch
"""

import difflib
import os
import re
import sys

PKG_DIR = 'package/kernel/mt76'
PATCH_OUT = os.path.join(PKG_DIR, 'patches', '996-mt7915-rxrate-sticky.patch')


def fail(msg):
    print('!!!! ' + msg)
    sys.exit(0)


def find_mt7915_main_c(build_root):
    """
    Find mt7915/main.c inside the mt76 PACKAGE build tree (target-*),
    skipping the kernel in-tree copy.
    """
    for dirpath, _dirs, files in os.walk(build_root):
        if 'main.c' not in files:
            continue
        norm = dirpath.replace('\\', '/')
        if '/target-' not in norm:
            continue
        if not norm.endswith('/mt7915') and '/mt7915/' not in norm:
            continue
        path = os.path.join(dirpath, 'main.c')
        try:
            with open(path, encoding='utf-8', errors='ignore') as fh:
                text = fh.read()
            if 'mt7915_sta_statistics' in text and 'mt7915_mcu_get_rx_rate' in text:
                return path, text
        except OSError:
            continue
    return None, None


def patch_rxrate(text):
    """
    Insert the idle-RX fallback into mt7915_sta_statistics().
    """
    is_crlf = '\r\n' in text
    t = text.replace('\r\n', '\n')

    # The upstream block, tab-indented:
    #     if (!mt7915_mcu_get_rx_rate(phy, vif, sta, &rxrate)) {
    #             sinfo->rxrate = rxrate;
    #             sinfo->filled |= BIT_ULL(NL80211_STA_INFO_RX_BITRATE);
    #     }
    pat = re.compile(
        r'(if \(!mt7915_mcu_get_rx_rate\(phy, vif, sta, &rxrate\)\) \{\n)'
        r'(\s*sinfo->rxrate = rxrate;\n)'
    )
    repl = (
        r'\1'
        r'\t\t/* Mercury: an idle station sends only base-rate control frames,\n'
        r'\t\t * so the queried RX rate collapses to 6 Mbit/s. Report the\n'
        r'\t\t * negotiated TX rate instead so the displayed RX reflects what\n'
        r'\t\t * the link can do - the sticky behaviour ath10k shows. During a\n'
        r'\t\t * real transfer the query returns an HT/VHT/HE rate (flags set)\n'
        r'\t\t * and is left untouched. */\n'
        r'\t\tif (!rxrate.flags && (txrate->flags || txrate->legacy))\n'
        r'\t\t\trxrate = *txrate;\n'
        r'\2'
    )
    t, n = pat.subn(repl, t)

    if is_crlf:
        t = t.replace('\n', '\r\n')
    return t, n


def relative_path(main_c_path):
    norm = main_c_path.replace('\\', '/')
    parts = norm.split('/')
    for i in range(len(parts) - 1, 0, -1):
        candidate = '/'.join(parts[:i])
        if os.path.exists(os.path.join(candidate, 'mt76.h')):
            return '/'.join(parts[i:])
    return '/'.join(parts[-2:])


def main():
    build_root = sys.argv[1] if len(sys.argv) > 1 else 'build_dir'

    if not os.path.isdir(PKG_DIR):
        fail('%s not found. Run from the openwrt/ directory.' % PKG_DIR)

    print('Searching for mt7915/main.c under %s ...' % build_root)
    path, old_text = find_mt7915_main_c(build_root)
    if path is None:
        fail(
            'mt7915/main.c not found under %s.\n'
            "Run 'make package/kernel/mt76/prepare V=s' first." % build_root
        )
    print('  found: %s' % path)

    rel = relative_path(path)
    print('  patch path (p1): %s' % rel)

    new_text, n = patch_rxrate(old_text)
    if n == 0:
        print('  WARNING: rxrate block not matched in mt7915/main.c - '
              'driver text may have moved. Skipping (cosmetic, non-fatal).')
        return
    if n != 1:
        fail('matched the rxrate block %d times, expected exactly 1' % n)

    diff_lines = list(difflib.unified_diff(
        old_text.splitlines(keepends=True),
        new_text.splitlines(keepends=True),
        fromfile='a/' + rel,
        tofile='b/' + rel,
        n=3,
    ))

    os.makedirs(os.path.dirname(PATCH_OUT), exist_ok=True)
    with open(PATCH_OUT, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write('# Mercury KM15-103H: report negotiated TX rate as RX rate when idle\n')
        fh.write('# Cosmetic - makes station-dump RX rate sticky like ath10k. Display only.\n')
        fh.write('\n')
        fh.writelines(diff_lines)

    print('  wrote: %s  (%d diff lines, 1 change)' % (PATCH_OUT, len(diff_lines)))


if __name__ == '__main__':
    main()
