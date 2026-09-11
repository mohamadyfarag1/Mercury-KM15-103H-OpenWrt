#!/usr/bin/env python3
import difflib, os, sys, re

PKG_DIR = 'package/kernel/mt76'
PATCH_OUT = os.path.join(PKG_DIR, 'patches', '998-mt7915-he160-dbdc.patch')

def find_mt7915_init_c(build_root):
    for dirpath, _dirs, files in os.walk(build_root):
        if 'init.c' not in files: continue
        norm = dirpath.replace('\\', '/')
        if '/target-' not in norm: continue
        if not norm.endswith('/mt7915'): continue
        path = os.path.join(dirpath, 'init.c')
        try:
            with open(path, encoding='utf-8', errors='ignore') as fh:
                text = fh.read()
            if "Can't do 160MHz with mt7915 dbdc" in text:
                return path, text
        except OSError:
            pass
    return None, None

def main():
    if len(sys.argv) < 2:
        print("Usage: %s <build_dir>" % sys.argv[0])
        sys.exit(0)
    
    path, text = find_mt7915_init_c(sys.argv[1])
    if not path or not text:
        print("gen_160_dbdc: mt7915/init.c with dbdc 160mhz guard not found.")
        sys.exit(0)
    
    is_crlf = '\r\n' in text
    t = text.replace('\r\n', '\n')
    
    # We want to change mphy->ext_phy->nss_160 = 0; to = 1;
    # But ONLY in the block guarding dbdc_support.
    
    new_text = re.sub(
        r'("Can.t do 160MHz with mt7915 dbdc\\n"\);\n\s*mphy->ext_phy->nss_160\s*=\s*)0;',
        r'\g<1>1; /* patched by mercury */',
        t, count=1
    )
    
    if new_text == t:
        print("gen_160_dbdc: Failed to regex-replace nss_160=0 in init.c")
        sys.exit(0)
        
    diff = list(difflib.unified_diff(
        t.splitlines(True),
        new_text.splitlines(True),
        fromfile='a/mt7915/init.c',
        tofile='b/mt7915/init.c'
    ))
    
    os.makedirs(os.path.dirname(PATCH_OUT), exist_ok=True)
    with open(PATCH_OUT, 'w', encoding='utf-8', newline='\n') as fh:
        fh.writelines(diff)
    
    print("gen_160_dbdc: generated %s" % PATCH_OUT)

if __name__ == '__main__':
    main()
