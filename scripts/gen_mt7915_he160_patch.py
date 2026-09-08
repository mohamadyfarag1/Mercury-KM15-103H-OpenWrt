#!/usr/bin/env python3
"""
Enable HE160 (802.11ax 160 MHz) and VHT160 for MT7915E in DBDC mode.

In upstream mt76 (mt7915/init.c), the driver restricts 160 MHz bandwidth
when DBDC mode is active (dev->dbdc_support) by zeroing out nss_160 and sts_160
and omitting VHT 160MHz flags.

This script patches mt7915/init.c during OpenWrt compilation to:
1. Enable VHT 160 MHz capability flags (IEEE80211_VHT_CAP_SUPP_CHAN_WIDTH_160MHZ,
   IEEE80211_VHT_CAP_SHORT_GI_160, and SUPPORTS_VHT_EXT_NSS_BW).
2. Set sts_160 /= 2 unconditionally for MT7915.
3. Set nss_160 = nss / 2 unconditionally for MT7915, unlocking HE160 in 5 GHz.

Run from the openwrt/ directory after:
    make package/kernel/mt76/prepare

Output: package/kernel/mt76/patches/998-mt7915-he160-dbdc.patch
"""

import difflib
import os
import re
import sys

PKG_DIR  = 'package/kernel/mt76'
PATCH_OUT = os.path.join(PKG_DIR, 'patches', '998-mt7915-he160-dbdc.patch')


def fail(msg):
    print('!!!! ' + msg)
    sys.exit(0)


def find_mt7915_init_c(build_root):
    """
    Find mt7915/init.c inside the mt76 PACKAGE build tree.
    Requires target- in the path to skip the kernel in-tree copy.
    """
    for dirpath, _dirs, files in os.walk(build_root):
        if 'init.c' not in files:
            continue
        # Must be the package tree (target-ARCH-...) not kernel in-tree
        norm = dirpath.replace('\\', '/')
        if '/target-' not in norm:
            continue
        # Must be inside the mt7915/ sub-directory of mt76
        if not norm.endswith('/mt7915') and '/mt7915/' not in norm:
            continue
        path = os.path.join(dirpath, 'init.c')
        try:
            with open(path, encoding='utf-8', errors='ignore') as fh:
                text = fh.read()
            if 'mt7915_init_wiphy' in text or 'mt7915_init_he_caps' in text:
                return path, text
        except OSError:
            continue
    return None, None


def patch_he160(text):
    """
    Apply 4 surgical replacements to unlock 160 MHz in mt7915/init.c.
    """
    is_crlf = '\r\n' in text
    t = text.replace('\r\n', '\n')
    changes = 0

    # 1. VHT 160 capability
    p1 = re.compile(
        r'(\t+if \(!dev->dbdc_support\)\n\t+vht_cap->cap \|=\n\t+IEEE80211_VHT_CAP_SHORT_GI_160 \|\n\t+FIELD_PREP\(IEEE80211_VHT_CAP_EXT_NSS_BW_MASK, 1\);)'
    )
    r1 = (
        r'\t\tvht_cap->cap |=\n'
        r'\t\t\tIEEE80211_VHT_CAP_SHORT_GI_160 |\n'
        r'\t\t\tIEEE80211_VHT_CAP_SUPP_CHAN_WIDTH_160MHZ |\n'
        r'\t\t\tFIELD_PREP(IEEE80211_VHT_CAP_EXT_NSS_BW_MASK, 1);'
    )
    t, n = p1.subn(r1, t)
    changes += n

    # 2. SUPPORTS_VHT_EXT_NSS_BW
    p2 = re.compile(
        r'(\t+if \(!is_mt7915\(&dev->mt76\) \|\| !dev->dbdc_support\)\n\t+ieee80211_hw_set\(hw, SUPPORTS_VHT_EXT_NSS_BW\);)'
    )
    r2 = r'\t\tieee80211_hw_set(hw, SUPPORTS_VHT_EXT_NSS_BW);'
    t, n = p2.subn(r2, t)
    changes += n

    # 3. sts_160 in mt7915_set_stream_he_txbf_caps
    p3 = re.compile(
        r'(\t+if \(is_mt7915\(&dev->mt76\)\) \{\n\t+if \(!dev->dbdc_support\)\n\t+sts_160 /= 2;\n\t+else\n\t+sts_160 = 0;\n\t+\})'
    )
    r3 = r'\tif (is_mt7915(&dev->mt76)) {\n\t\tsts_160 /= 2;\n\t}'
    t, n = p3.subn(r3, t)
    changes += n

    # 4. nss_160 in mt7915_init_he_caps
    p4 = re.compile(
        r'(\t+else if \(!dev->dbdc_support\)\n\t+/\* Can do 1/2 of NSS streams in 160Mhz mode for mt7915 \*/\n\t+nss_160 = nss / 2;\n\t+else\n\t+/\* Can\'t do 160MHz with mt7915 dbdc \*/\n\t+nss_160 = 0;)'
    )
    r4 = (
        r'\telse\n'
        r'\t\t/* Force 1/2 of NSS streams for 160MHz mode in DBDC */\n'
        r'\t\tnss_160 = nss / 2;'
    )
    t, n = p4.subn(r4, t)
    changes += n

    if is_crlf:
        t = t.replace('\n', '\r\n')
    return t, changes


def relative_path(init_c_path):
    """
    Derive the path used inside the patch header: a/mt7915/init.c / b/mt7915/init.c
    """
    norm = init_c_path.replace('\\', '/')
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

    print('Searching for mt7915/init.c under %s ...' % build_root)
    path, old_text = find_mt7915_init_c(build_root)
    if path is None:
        fail(
            'mt7915/init.c not found under %s.\n'
            "Run 'make package/kernel/mt76/prepare V=s' first." % build_root
        )
    print('  found: %s' % path)

    rel = relative_path(path)
    print('  patch path (p1): %s' % rel)

    new_text, n_changes = patch_he160(old_text)
    if n_changes == 0:
        print('  WARNING: No HE160 pattern matched in mt7915/init.c.')
        return

    diff_lines = list(difflib.unified_diff(
        old_text.splitlines(keepends=True),
        new_text.splitlines(keepends=True),
        fromfile='a/' + rel,
        tofile='b/' + rel,
        n=3,
    ))

    os.makedirs(os.path.dirname(PATCH_OUT), exist_ok=True)
    with open(PATCH_OUT, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write('# Mercury KM15-103H: force HE160 and VHT160 capability on MT7915 in DBDC\n')
        fh.write('# Unlocks 160 MHz bandwidth in mt7915 driver for 802.11ax\n')
        fh.write('\n')
        fh.writelines(diff_lines)

    print('  wrote: %s  (%d diff lines, %d change(s))' % (PATCH_OUT, len(diff_lines), n_changes))


if __name__ == '__main__':
    main()
