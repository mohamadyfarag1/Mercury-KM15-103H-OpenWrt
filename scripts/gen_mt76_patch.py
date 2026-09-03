#!/usr/bin/env python3
"""
Extend the mt76 channel tables in mt76/mac80211.c and emit the result as
an OpenWrt package patch.

5 GHz (always): mt76_channels_5ghz[] goes from the stock ~28-channel
20 MHz-spaced table to a 68-channel 10 MHz-spaced table, 5180-5885 MHz.
Same channel plan as the Horus/ath10k build.

2.3 GHz (opt-in, MERCURY_ENABLE_23GHZ=1): prepends channels -19..-1
(2312-2402 MHz) to mt76_channels_2ghz[].  OFF by default - see the
"2.3 GHz" note at the bottom of this docstring.

WHY A PATCH FILE AND NOT AN IN-PLACE EDIT
-----------------------------------------
An edit made to the prepared tree under build_dir is undone the moment
OpenWrt re-runs Build/Prepare for the package.  Writing a real patch
into package/kernel/mt76/patches/ makes OpenWrt apply it itself on
every unpack.  mt76 has no BUILD_VARIANT, so unlike ath10k-ct one
patch file covers every build - there is no variant-directory trap.

PATCH PATHS
-----------
OpenWrt applies package patches with `patch -p1` from INSIDE the
package build directory, so the diff header must be
    --- a/mac80211.c
    +++ b/mac80211.c
NOT the full build_dir/... path.  mac80211.c sits at the top level of
the mt76 source tree, so the relative path is just the basename.

Run from the openwrt/ directory after:
    make package/kernel/mt76/prepare

2.3 GHz
-------
Adding the channels to the table and to the regdb is easy, and they
will show up in `iw phy info`.  Whether the MT7915E actually RADIATES
there is a separate, hardware question: the PA, the RF band-pass
filters and the antenna match are all built for 2.400-2.4835 GHz, the
EEPROM carries no calibration below 2.4 GHz, and the MT7915 MCU may
simply reject an out-of-band channel switch.  Because the whole point
of this build is "real frequencies, not just numbers", these channels
stay OFF unless explicitly requested, and must be measured on the
device before they are trusted.
"""

import difflib
import os
import re
import sys

# ---------------------------------------------------------------------
# 5 GHz: same channel plan as Horus/ath10k.
# 5 GHz channel N sits at 5000 + N*5 MHz.
#   range(36, 147, 2)  -> 36, 38 ... 146   (56 ch, UNII-1..UNII-2e)
#   range(149, 166, 2) -> 149, 151 ... 165 ( 9 ch, UNII-3)
#   [169, 173, 177]                        ( 3 ch, UNII-4 / extended)
# Total 68.
# ---------------------------------------------------------------------
CHANS_5G = list(range(36, 147, 2)) + list(range(149, 166, 2)) + [169, 173, 177]

# ---------------------------------------------------------------------
# 2.3 GHz: 2 GHz channel N sits at 2407 + N*5 MHz, so sub-2.4 GHz
# channels carry NEGATIVE numbers: 2312 MHz is channel -19, 2402 MHz is
# channel -1.  net/wireless/util.c needs the companion
# `chan = (int)(char)chan;` patch (mercury-07-superchannel.sh) for the
# kernel to map those numbers back to frequencies correctly.
# ---------------------------------------------------------------------
CHANS_23G = list(range(-19, 0))          # -19 .. -1  => 2312 .. 2402 MHz

ENABLE_23G = os.environ.get('MERCURY_ENABLE_23GHZ', '').strip() in ('1', 'yes', 'true')

PKG_DIR = 'package/kernel/mt76'
PATCH_REL = os.path.join('patches', '999-mercury-superchannels.patch')

# Matches a real array entry - CHAN5G(36, 5180) - but NOT the macro
# definition CHAN5G(_idx, _freq), because those args are identifiers.
ENTRY_RE_5G = re.compile(r'CHAN5G\(\s*-?\d+\s*,\s*\d+\s*\)')
ENTRY_RE_2G = re.compile(r'CHAN2G\(\s*-?\d+\s*,\s*\d+\s*\)')


def freq_5g(ch):
    return 5000 + ch * 5


def freq_2g(ch):
    return 2407 + ch * 5


def fail(msg):
    print('!!!! ' + msg)
    sys.exit(1)


def find_mt76_mac80211(build_root):
    """
    Return (path, text) for the mt76 mac80211.c that defines the channel
    tables.  The mac80211 backports tree also has a mac80211.c; requiring
    BOTH mt76_channels_5ghz and mt76_channels_2ghz excludes it.
    """
    for dirpath, _dirs, files in os.walk(build_root):
        if 'mac80211.c' not in files:
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


def replace_array(text, name, macro, chans, freq_fn):
    """
    Replace `static const struct ieee80211_channel <name>[] = { ... };`
    with an array built from `chans`.  Whitespace-tolerant so a
    reformatted upstream file still matches.  Returns the new text.
    """
    entries = '\n'.join(
        '\t%s(%d, %d),' % (macro, ch, freq_fn(ch)) for ch in chans
    )
    replacement = (
        'static const struct ieee80211_channel %s[] = {\n%s\n};' % (name, entries)
    )
    pattern = (
        r'static\s+const\s+struct\s+ieee80211_channel\s+'
        + re.escape(name)
        + r'\s*\[\s*\]\s*=\s*\{.*?\};'
    )
    new_text, n = re.subn(pattern, replacement, text, flags=re.DOTALL)
    if n != 1:
        fail('found %d match(es) for %s[] - expected exactly 1' % (n, name))
    return new_text


def main():
    build_root = sys.argv[1] if len(sys.argv) > 1 else 'build_dir'

    if not os.path.isdir(PKG_DIR):
        fail('%s does not exist - is this an OpenWrt checkout with the '
             'mt76 package? (run from the openwrt/ directory)' % PKG_DIR)

    print('Searching for mt76/mac80211.c under %s ...' % build_root)
    path, old_text = find_mt76_mac80211(build_root)
    if path is None:
        fail('mt76/mac80211.c (defining mt76_channels_5ghz and '
             'mt76_channels_2ghz) not found under %s.\n'
             "     Run 'make package/kernel/mt76/prepare V=s' first." % build_root)

    print('  found  : %s' % path)

    # OpenWrt applies package patches with -p1 from inside the package
    # build directory. mac80211.c is at the top level of the mt76 tree,
    # so the in-patch path is the bare basename. Assert that assumption
    # rather than silently emitting a patch that can never apply.
    rel = os.path.basename(path)
    pkg_root = os.path.dirname(path)
    if not os.path.exists(os.path.join(pkg_root, 'mt76.h')):
        fail('%s does not look like the mt76 source root (no mt76.h '
             'beside mac80211.c). The patch path would be wrong.' % pkg_root)

    stock_5g = len(ENTRY_RE_5G.findall(old_text))
    stock_2g = len(ENTRY_RE_2G.findall(old_text))
    print('  stock  : %d x 5 GHz, %d x 2.4 GHz channels' % (stock_5g, stock_2g))

    # --- 5 GHz: always ------------------------------------------------
    new_text = replace_array(
        old_text, 'mt76_channels_5ghz', 'CHAN5G', CHANS_5G, freq_5g)

    # --- 2.3 GHz: opt-in ----------------------------------------------
    chans_2g = None
    if ENABLE_23G:
        # Keep every stock 2.4 GHz channel and prepend the 2.3 GHz ones,
        # so nothing that works today is lost.
        stock_nums = [
            int(m.group(1))
            for m in re.finditer(
                r'CHAN2G\(\s*(-?\d+)\s*,\s*\d+\s*\)', old_text)
        ]
        if not stock_nums:
            fail('could not read the stock 2.4 GHz channel numbers')
        chans_2g = CHANS_23G + stock_nums

        def freq_2g_mixed(ch):
            # Channel 14 is the documented exception to 2407 + N*5.
            return 2484 if ch == 14 else freq_2g(ch)

        new_text = replace_array(
            new_text, 'mt76_channels_2ghz', 'CHAN2G', chans_2g, freq_2g_mixed)
        print('  2.3GHz : ENABLED - added %d channels (%d-%d MHz)' % (
            len(CHANS_23G), freq_2g(CHANS_23G[0]), freq_2g(CHANS_23G[-1])))
        print('           EXPERIMENTAL: MT7915E RF front end is built for')
        print('           2.400-2.4835 GHz and has no EEPROM calibration')
        print('           below 2.4 GHz. Measure before trusting these.')
    else:
        print('  2.3GHz : disabled (set MERCURY_ENABLE_23GHZ=1 to include)')

    # --- verify the substitution actually produced what we asked for ---
    got_5g = len(ENTRY_RE_5G.findall(new_text))
    if got_5g != len(CHANS_5G):
        fail('after substitution got %d 5 GHz entries, expected %d'
             % (got_5g, len(CHANS_5G)))
    if chans_2g is not None:
        got_2g = len(ENTRY_RE_2G.findall(new_text))
        if got_2g != len(chans_2g):
            fail('after substitution got %d 2.4 GHz entries, expected %d'
                 % (got_2g, len(chans_2g)))

    if new_text == old_text:
        fail('no change produced - refusing to write an empty patch')

    # --- emit the patch -----------------------------------------------
    diff_lines = list(difflib.unified_diff(
        old_text.splitlines(keepends=True),
        new_text.splitlines(keepends=True),
        fromfile='a/' + rel,
        tofile='b/' + rel,
        n=3,
    ))

    patch_path = os.path.join(PKG_DIR, PATCH_REL)
    os.makedirs(os.path.dirname(patch_path), exist_ok=True)
    with open(patch_path, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write('# Mercury KM15-103H superchannel table\n')
        fh.write('# 5 GHz : %d channels, %d-%d MHz (10 MHz spacing)\n'
                 % (len(CHANS_5G), freq_5g(CHANS_5G[0]), freq_5g(CHANS_5G[-1])))
        if chans_2g is not None:
            fh.write('# 2.3GHz: %d channels, %d-%d MHz (EXPERIMENTAL, unverified on hardware)\n'
                     % (len(CHANS_23G), freq_2g(CHANS_23G[0]), freq_2g(CHANS_23G[-1])))
        fh.write('\n')
        fh.writelines(diff_lines)
    print('  wrote  : %s  (%d diff lines)' % (patch_path, len(diff_lines)))

    # --- frequency list for the build-time drift check ----------------
    os.makedirs('tmp', exist_ok=True)
    with open('tmp/mercury-driver-freqs.txt', 'w') as fh:
        for ch in CHANS_5G:
            fh.write('%d\n' % freq_5g(ch))
        if chans_2g is not None:
            for ch in CHANS_23G:
                fh.write('%d\n' % freq_2g(ch))
    print('  freqs  : tmp/mercury-driver-freqs.txt')
    print('  result : 5 GHz %d -> %d channels' % (stock_5g, got_5g))


if __name__ == '__main__':
    main()
