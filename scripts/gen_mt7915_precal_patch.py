#!/usr/bin/env python3
"""
Generate mt7915 precal fallback patch for mt76 driver.

In upstream mt76 (mt7915/eeprom.c), mt7915_eeprom_load_precal only attempts to
load precal data from MTD partition or NVMEM cell ("precal"). If the flash
partition is missing, wiped, corrupted, or replaced with dummy bootloader data,
the driver emits:
    mt7915e: missing precal data, size=105488
and leaves dev->cal = NULL. Without RF pre-calibration data, the MT7915 MCU
times out on radio configuration (message 00004eed timeout), bringing down
the 2.4 GHz AP (Tx-Power 0 dBm) and causing recurring hardware resets on 5 GHz.

This script patches mt7915/eeprom.c to:
1. Fall back to loading the 105,488 bytes of precal data from the default
   firmware binary (mt7915_eeprom_dbdc.bin) at offset 0xe10 when MTD/NVMEM fails.
2. Ensure dev->flash_mode = true in mt7915_eeprom_load_default so precal loading
   is always triggered.

Run from the openwrt/ directory after:
    make package/kernel/mt76/prepare

Output: package/kernel/mt76/patches/997-mt7915-precal-fallback.patch
"""

import difflib
import os
import re
import sys

PKG_DIR = 'package/kernel/mt76'
PATCH_OUT = os.path.join(PKG_DIR, 'patches', '997-mt7915-precal-fallback.patch')


def fail(msg):
    print('!!!! ' + msg)
    sys.exit(1)


def find_mt7915_eeprom_c(build_root):
    """
    Find mt7915/eeprom.c inside the mt76 PACKAGE build tree.
    Requires target- in the path to skip the kernel in-tree copy.
    """
    for dirpath, _dirs, files in os.walk(build_root):
        if 'eeprom.c' not in files:
            continue
        norm = dirpath.replace('\\', '/')
        if '/target-' not in norm:
            continue
        if not norm.endswith('/mt7915') and '/mt7915/' not in norm:
            continue
        path = os.path.join(dirpath, 'eeprom.c')
        try:
            with open(path, encoding='utf-8', errors='ignore') as fh:
                text = fh.read()
            if 'mt7915_eeprom_load_precal' in text:
                return path, text
        except OSError:
            continue
    return None, None


def patch_precal(text):
    """
    Add fallback to mt7915_eeprom_load_precal in mt7915/eeprom.c.
    """
    is_crlf = '\r\n' in text
    t = text.replace('\r\n', '\n')
    changes = 0

    # 1. Add variable declarations in mt7915_eeprom_load_precal
    p1 = re.compile(r'(\tu32 size, val = eeprom\[offs\];\n\tint ret;)')
    r1 = r'\1\n\tconst struct firmware *fw = NULL;\n\tconst char *name;'
    t, n = p1.subn(r1, t)
    changes += n

    # 2. Add fallback before dev_warn in mt7915_eeprom_load_precal
    p2 = re.compile(r'(\t+)(dev_warn\(mdev->dev, "missing precal data, size=%d\\n", size\);)')
    r2 = (
        r'\tname = mt7915_eeprom_name(dev);\n'
        r'\tif (name && !request_firmware(&fw, name, dev->mt76.dev)) {\n'
        r'\t\tif (fw && fw->size >= offs + size) {\n'
        r'\t\t\tmemcpy(dev->cal, fw->data + offs, size);\n'
        r'\t\t\trelease_firmware(fw);\n'
        r'\t\t\tdev_info(mdev->dev, "loaded precal data from %s, size=%d\\n", name, size);\n'
        r'\t\t\treturn 0;\n'
        r'\t\t}\n'
        r'\t\trelease_firmware(fw);\n'
        r'\t}\n\n'
        r'\1\2'
    )
    t, n = p2.subn(r2, t)
    changes += n

    # 3. Ensure dev->flash_mode = true in mt7915_eeprom_load_default
    if 'dev->flash_mode = true;' not in t:
        p3 = re.compile(r'(memcpy\(eeprom, fw->data, mt7915_eeprom_size\(dev\)\);)')
        r3 = r'\1\n\tdev->flash_mode = true;'
        t, n = p3.subn(r3, t)
        changes += n

    if is_crlf:
        t = t.replace('\n', '\r\n')
    return t, changes


def relative_path(eeprom_c_path):
    norm = eeprom_c_path.replace('\\', '/')
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

    print('Searching for mt7915/eeprom.c under %s ...' % build_root)
    path, old_text = find_mt7915_eeprom_c(build_root)
    if path is None:
        fail(
            'mt7915/eeprom.c not found under %s.\n'
            "Run 'make package/kernel/mt76/prepare V=s' first." % build_root
        )
    print('  found: %s' % path)

    rel = relative_path(path)
    print('  patch path (p1): %s' % rel)

    new_text, n_changes = patch_precal(old_text)
    if n_changes == 0:
        print('  WARNING: No precal pattern matched in mt7915/eeprom.c.')
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
        fh.write('# Mercury KM15-103H: fallback to precal in mt7915_eeprom_dbdc.bin\n')
        fh.write('# Ensures RF calibration data is always loaded even if flash MTD2 is uncalibrated\n')
        fh.write('\n')
        fh.writelines(diff_lines)

    print('  wrote: %s  (%d diff lines, %d change(s))' % (PATCH_OUT, len(diff_lines), n_changes))


if __name__ == '__main__':
    main()
