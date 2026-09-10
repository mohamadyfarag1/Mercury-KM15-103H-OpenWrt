#!/usr/bin/env python3

import os
import re
import sys
import difflib

PKG_DIR = 'package/kernel/mt76'
PATCH_OUT = os.path.join(PKG_DIR, 'patches', '998-mt7915-he160-dbdc.patch')

def fail(msg):
    print('!!!! ' + msg)
    sys.exit(1)

def find_init_c(build_root):
    for dirpath, _dirs, files in os.walk(build_root):
        if 'init.c' not in files:
            continue
        norm = dirpath.replace('\\', '/')
        if '/target-' not in norm or '/mt7915' not in norm:
            continue
        return os.path.join(dirpath, 'init.c')
    return None

def main():
    build_root = sys.argv[1] if len(sys.argv) > 1 else 'build_dir'
    path = find_init_c(build_root)
    if not path:
        fail("mt7915/init.c not found under %s" % build_root)

    with open(path, encoding='utf-8') as f:
        t = f.read()

    # Patch 1: Remove VHT EXT NSS BW restriction
    # if (!is_mt7915(&dev->mt76) || !dev->dbdc_support) -> if (!is_mt7915(&dev->mt76) || 1)
    new_text = re.sub(r'if \(!is_mt7915\(&dev->mt76\) \|\| !dev->dbdc_support\)',
                      r'if (!is_mt7915(&dev->mt76) || 1)', t)

    # Patch 2: Remove HE160 DBDC check
    # else if (!dev->dbdc_support) -> else if (1)
    # nss_160 = nss / 2;
    # else
    # nss_160 = 0;
    pattern = r'else if \(!dev->dbdc_support\)(\s*/\*.*?\*/\s*nss_160\s*=\s*nss\s*/\s*2;\s*)else(\s*/\*.*?\*/\s*nss_160\s*=\s*0;)'
    new_text, n = re.subn(pattern, r'else if (1)\1', new_text, flags=re.DOTALL)

    if new_text == t or n == 0:
        fail('No changes applied to init.c. Pattern mismatch.')

    rel = os.path.basename(path)
    diff_lines = list(difflib.unified_diff(
        t.splitlines(keepends=True),
        new_text.splitlines(keepends=True),
        fromfile='a/mt7915/' + rel, tofile='b/mt7915/' + rel, n=3))

    os.makedirs(os.path.dirname(PATCH_OUT), exist_ok=True)
    with open(PATCH_OUT, 'w', encoding='utf-8') as f:
        f.write('# Mercury KM15-103H: Force HE160 support in DBDC mode\n\n')
        f.writelines(diff_lines)
    
    print('Generated %s' % PATCH_OUT)

if __name__ == '__main__':
    main()
