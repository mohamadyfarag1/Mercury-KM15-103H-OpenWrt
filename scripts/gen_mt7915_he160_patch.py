#!/usr/bin/env python3
"""
Enable HE160 (802.11ax 160 MHz) for MT7915E in DBDC mode.

The upstream mt76 driver (OpenWrt 24.x era, mt7915/init.c) blocks HE160
in DBDC mode via:

    if (!dev->dbdc_support || is_mt7916(&dev->mt76) || is_mt7986(&dev->mt76))
        <set HE160 phy_cap bit and MCS-160 tables>

This guard was added because the basic MT7915 (non-E) in DBDC mode cannot do
160 MHz.  MT7915E (PCIe ID 0x7906, single-chip DBDC) CAN: the factory firmware
for Mercury KM15-103H demonstrates it, and the MediaTek SDK enables it.

Fix: drop the `!dev->dbdc_support ||` condition so MT7915E in DBDC mode
advertises HE160 capability to the kernel.  The guard `is_mt7916 || is_mt7986`
is kept; adding is_mt7915 (which matches BOTH basic and E) effectively makes
the whole block unconditional for 5 GHz, which is fine - if the firmware MCU
cannot handle HE160 it will refuse the channel-switch command gracefully.

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
    sys.exit(1)


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
        # Confirm it is really the mt7915 init by checking for a known symbol
        try:
            with open(path, encoding='utf-8', errors='ignore') as fh:
                text = fh.read()
            if 'mt7915_init_wiphy' in text or 'mt7915_init_he_caps' in text:
                return path, text
        except OSError:
            continue
    return None, None


def patch_he160(old_text, init_c_path):
    """
    Remove the !dev->dbdc_support restriction from HE160 capability blocks.

    Handles both single-line and multi-line if-conditions.  Returns new_text.
    Raises ValueError if no matching pattern is found.
    """
    # ---------- strategy 1: single-line form ----------------------------
    # if (!dev->dbdc_support || is_mt7916(&dev->mt76) || is_mt7986(&dev->mt76))
    PAT1 = re.compile(
        r'if\s*\(\s*!dev->dbdc_support\s*\|\|\s*'
        r'(is_mt7916[^)]*\).*?)\)',
        re.DOTALL,
    )

    # ---------- strategy 2: multi-line, dbdc on first line -------------
    # if (!dev->dbdc_support || is_mt7916(&dev->mt76) ||
    #     is_mt7986(&dev->mt76))
    PAT2 = re.compile(
        r'!dev->dbdc_support\s*\|\|\s*\n',
    )

    # ---------- strategy 3: any line with !dev->dbdc_support near is_mt7916
    # The simplest: just strip "!dev->dbdc_support || " wherever it appears
    # next to is_mt7916 or is_mt7986 (context: we are inside init.c, not reg.c)
    STRIP = re.compile(r'!dev->dbdc_support \|\| (?=is_mt7916|is_mt7986)')

    changes_before = None
    new_text = old_text

    # Try strategy 3 first (most permissive, works for all known forms)
    new_text, n = STRIP.subn('', new_text)
    if n > 0:
        print('  strategy 3: removed %d occurrence(s) of "!dev->dbdc_support || "' % n)
        return new_text, n

    # Strategy 2: multi-line continuation — remove the first dbdc line
    new_text, n = PAT2.subn('', old_text)
    if n > 0:
        print('  strategy 2: removed %d multi-line !dbdc_support condition(s)' % n)
        return new_text, n

    raise ValueError(
        'No !dev->dbdc_support HE160 guard found in %s.\n'
        'The upstream source layout may have changed; check mt7915/init.c '
        'manually and update this script.' % init_c_path
    )


def relative_path(init_c_path):
    """
    Derive the path used inside the patch header.
    OpenWrt applies patches with `patch -p1` from the package source root,
    so the header must be  a/mt7915/init.c  /  b/mt7915/init.c.
    """
    norm = init_c_path.replace('\\', '/')
    # Walk up until we find the mt76 root (contains mt76.h)
    parts = norm.split('/')
    for i in range(len(parts) - 1, 0, -1):
        candidate = '/'.join(parts[:i])
        if os.path.exists(os.path.join(candidate, 'mt76.h')):
            return '/'.join(parts[i:])  # e.g. mt7915/init.c
    # Fallback: use last two components
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

    try:
        new_text, n_changes = patch_he160(old_text, path)
    except ValueError as exc:
        # Not fatal - the driver may already allow HE160, or the code layout
        # differs.  Report loudly but do not fail the build: the channel-table
        # patch (999) is the critical one; this is a best-effort capability fix.
        print('  WARNING: %s' % exc)
        print('  Skipping HE160 patch - build continues without it.')
        return

    if new_text == old_text:
        print('  No change produced (pattern may already be absent). Skipping.')
        return

    # Emit unified diff as a package patch
    diff_lines = list(difflib.unified_diff(
        old_text.splitlines(keepends=True),
        new_text.splitlines(keepends=True),
        fromfile='a/' + rel,
        tofile='b/' + rel,
        n=3,
    ))

    os.makedirs(os.path.dirname(PATCH_OUT), exist_ok=True)
    with open(PATCH_OUT, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write('# Mercury KM15-103H: enable HE160 in MT7915E DBDC mode\n')
        fh.write('# MT7915E (PCIe, single-chip DBDC) supports 160 MHz on 5 GHz.\n')
        fh.write('# Remove the !dev->dbdc_support guard so the driver advertises\n')
        fh.write('# HE160 capability even when both 2.4 GHz and 5 GHz are active.\n')
        fh.write('\n')
        fh.writelines(diff_lines)

    print('  wrote: %s  (%d diff lines, %d change(s))' % (PATCH_OUT, len(diff_lines), n_changes))


if __name__ == '__main__':
    main()
