#!/usr/bin/env python3
"""
Generate a patch for mt7915/eeprom.c to prevent txpower from dropping to 0
for channels that do not have EEPROM calibration data (like out-of-band super channels).

This patches mt7915_eeprom_get_target_power to enforce a default minimum of 40 (20 dBm)
if the lookup returns 0 (which it does for uncalibrated out-of-band groups).
"""

import difflib
import os
import re
import sys

PKG_DIR = 'package/kernel/mt76'
PATCH_OUT = os.path.join(PKG_DIR, 'patches', '998-mt7915-txpower-fallback.patch')

def fail(msg):
    print('!!!! ' + msg)
    sys.exit(0)

def find_mt7915_eeprom_c(build_root):
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
            if 'mt7915_eeprom_get_target_power' in text:
                return path, text
        except OSError:
            continue
    return None, None

def patch_txpower(text):
    is_crlf = '\r\n' in text
    t = text.replace('\r\n', '\n')
    changes = 0

    p = re.compile(r'(\t\}\n\n)(\treturn target_power;\n\})')
    r = r'\1\t/* Mercury KM15-103H: If channel is uncalibrated, force 20 dBm (40 half-dBm) */\n\tif (target_power == 0 || target_power == 0xff)\n\t\ttarget_power = 40;\n\n\2'
    
    t, n = p.subn(r, t)
    changes += n

    if is_crlf:
        t = t.replace('\n', '\r\n')
    return t, changes

def relative_path(eeprom_c_path):
    norm = eeprom_c_path.replace('\\', '/')
    parts = norm.split('/')
    for i in range(len(parts) - 1, 0, -1):
        if os.path.exists(os.path.join('/'.join(parts[:i]), 'mt76.h')):
            return '/'.join(parts[i:])
    return '/'.join(parts[-2:])

def main():
    build_root = sys.argv[1] if len(sys.argv) > 1 else 'build_dir'

    if not os.path.isdir(PKG_DIR):
        fail('%s not found. Run from the openwrt/ directory.' % PKG_DIR)

    path, old_text = find_mt7915_eeprom_c(build_root)
    if path is None:
        fail("mt7915/eeprom.c not found")
        
    rel = relative_path(path)
    new_text, n_changes = patch_txpower(old_text)
    
    if n_changes == 0:
        print('  WARNING: No txpower pattern matched.')
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
        fh.write('# Mercury KM15-103H: enforce minimum txpower for uncalibrated out-of-band channels\n')
        fh.write('\n')
        fh.writelines(diff_lines)

    print('  wrote: %s' % PATCH_OUT)

if __name__ == '__main__':
    main()
