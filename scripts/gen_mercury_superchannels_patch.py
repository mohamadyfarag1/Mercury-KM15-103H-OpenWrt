#!/usr/bin/env python3
import difflib, os, sys, re

PKG_DIR = 'package/kernel/mt76'
PATCH_OUT = os.path.join(PKG_DIR, 'patches', '999-mercury-superchannels.patch')

def find_mac80211_c(build_root):
    for dirpath, _dirs, files in os.walk(build_root):
        if 'mac80211.c' not in files: continue
        norm = dirpath.replace('\\', '/')
        if '/target-' not in norm: continue
        if not norm.endswith('/mt76'): continue
        path = os.path.join(dirpath, 'mac80211.c')
        try:
            with open(path, encoding='utf-8', errors='ignore') as fh:
                text = fh.read()
            if "mt76_channels_5ghz[]" in text:
                return path, text
        except OSError:
            pass
    return None, None

def main():
    if len(sys.argv) < 2:
        print("Usage: %s <build_dir>" % sys.argv[0])
        sys.exit(0)
    
    path, text = find_mac80211_c(sys.argv[1])
    if not path or not text:
        print("gen_superchannels: mt76/mac80211.c not found.")
        sys.exit(0)
    
    is_crlf = '\r\n' in text
    t = text.replace('\r\n', '\n')
    
    # We want to append to the end of mt76_channels_5ghz[]
    # The array ends with something like CHAN5G(177, 5885), \n };
    # or just CHAN5G(165, 5825), \n };
    
    extra_channels = """
	CHAN5G(169, 5845),
	CHAN5G(173, 5865),
	CHAN5G(177, 5885),
	CHAN5G(184, 4920),
	CHAN5G(188, 4940),
	CHAN5G(192, 4960),
	CHAN5G(196, 4980),
"""
    
    # Regex to find the closing brace of mt76_channels_5ghz
    new_text = re.sub(
        r'(static const struct ieee80211_channel mt76_channels_5ghz\[\] = \{[\s\S]*?CHAN5G[^\}]*?)(\n};)',
        r'\g<1>' + extra_channels + r'};',
        t, count=1
    )
    
    if new_text == t:
        print("gen_superchannels: Failed to inject channels into mt76_channels_5ghz")
        sys.exit(0)
        
    diff = list(difflib.unified_diff(
        t.splitlines(True),
        new_text.splitlines(True),
        fromfile='a/mac80211.c',
        tofile='b/mac80211.c'
    ))
    
    os.makedirs(os.path.dirname(PATCH_OUT), exist_ok=True)
    with open(PATCH_OUT, 'w', encoding='utf-8', newline='\n') as fh:
        fh.writelines(diff)
    
    print("gen_superchannels: generated %s" % PATCH_OUT)

if __name__ == '__main__':
    main()
