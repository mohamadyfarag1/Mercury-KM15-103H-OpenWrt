#!/bin/bash
# =============================================
# Script 6: Generate Custom Unlocked Regulatory DB
# =============================================
# Runs from the repository root. Clones wireless-regdb, generates
# a db.txt that gives every country the STANDARD 2.4/5 GHz channel
# plan at 30 dBm with no DFS flag and no NO_IR, signs it, and drops
# the resulting regulatory.db into openwrt/files/ so OpenWrt bundles
# it into the squashfs instead of the stock restricted one.
#
# The point of the custom database is uniform power and no radar
# hold-off across countries - NOT extra spectrum. Channels outside
# the standard plan have no EEPROM calibration on the MT7915E and
# were removed after every one of them failed at AP bring-up.
# =============================================
set -e

echo "======================================="
echo "Generating Unlocked Regulatory Database"
echo "======================================="

if [ ! -d "wireless-regdb" ]; then
    git clone https://git.kernel.org/pub/scm/linux/kernel/git/sforshee/wireless-regdb.git
fi
cd wireless-regdb

python3 - <<'PYEOF'
import os

# 2.3 GHz is opt-in. When MERCURY_ENABLE_23GHZ is set the 2.4 GHz rule floor
# drops from 2402 to 2302 so ch-19 (2312 MHz) has room for its 20 MHz
# (2302-2322). Off by default - the standard rule starts at 2402.
_e = os.environ.get('MERCURY_ENABLE_23GHZ', '').strip().lower()
ENABLE_23G = _e not in ('', '0', 'no', 'false', 'disable')
GHZ24_FLOOR = 2302 if ENABLE_23G else 2402

countries = [
    '00',
    'AD','AE','AF','AL','AM','AN','AR','AT','AU','AW','AZ',
    'BA','BB','BD','BE','BG','BH','BL','BN','BO','BR','BY',
    'CA','CF','CH','CI','CL','CN','CO','CR','CY','CZ',
    'DE','DK','DO','DZ',
    'EC','EE','EG','ES','ET',
    'FI','FR',
    'GB','GE','GH','GL','GP','GR','GT','GU','GY',
    'HK','HN','HR','HT','HU',
    'ID','IE','IL','IN','IQ','IR','IS','IT',
    'JM','JO','JP',
    'KE','KH','KN','KP','KR','KW','KY','KZ',
    'LB','LC','LI','LK','LS','LT','LU','LV',
    'MA','MC','MD','ME','MF','MH','MK','MN','MO','MP','MQ','MR','MT','MU','MW','MX','MY',
    'NG','NI','NL','NO','NP','NZ',
    'OM',
    'PA','PE','PF','PG','PH','PK','PL','PM','PR','PT','PW','PY',
    'QA',
    'RE','RO','RS','RU','RW',
    'SA','SE','SG','SI','SK','SN','SR','SV','SY',
    'TC','TD','TG','TH','TN','TR','TT','TW','TZ',
    'UA','UG','US','UY','UZ',
    'VC','VE','VI','VN','VU',
    'WF','WS',
    'YE','YT',
    'ZA','ZW',
]
with open('db.txt', 'w') as f:
    for c in countries:
        f.write('country %s:\n' % c)
        # Standard channel plan only. A rule must contain the whole channel,
        # not just its centre: cfg80211 disables any channel whose centre ± 10
        # MHz falls outside, which is exactly why the old 5100 floor killed the
        # bottom of the band ("Frequency 5100 (secondary) not allowed for AP
        # mode") even though 5100 was nominally inside the rule. Every edge
        # below is therefore a real band edge, not a channel centre.
        #   2402-2482  : 2.4 GHz ch1-13
        #   5140-5330  : lower UNII-1 edge + UNII-1 + UNII-2A, ch30-64
        #   5490-5730  : UNII-2C, ch100-144
        #   5735-5895  : UNII-3 + UNII-4, ch149-177
        # The low rule starts at 5140, not 5170, to cover the 5 MHz-grid
        # table (995-mt7915-5ghz-grid.patch), whose lowest channel is ch30
        # (5150 MHz). A rule must contain the whole channel: ch30 at 5150
        # spans 5140-5160 at 20 MHz, so the floor is 5150 - 10 = 5140. This
        # is exactly the edge the old 5100 floor got wrong - the floor is a
        # channel EDGE, never a channel centre. The three rules match the
        # grid's three sub-bands one-to-one; the DFS void 5330-5490 is left
        # ungranted so the grid deliberately skips it.
        # The top rule reaches 5895 because the grid ends at ch177 (5885
        # MHz); ch177's 20 MHz needs 5885 + 10 = 5895.
        f.write('\t(%d - 2482 @ 40), (30)\n' % GHZ24_FLOOR)
        f.write('\t(5140 - 5330 @ 160), (30)\n')
        f.write('\t(5490 - 5730 @ 160), (30)\n')
        f.write('\t(5735 - 5895 @ 80), (30)\n')
        f.write('\n')
print('Generated db.txt with %d countries (2.4 GHz floor %d MHz, 2.3 GHz %s)'
      % (len(countries), GHZ24_FLOOR, 'ON' if ENABLE_23G else 'off'))
PYEOF

openssl ecparam -name prime256v1 -genkey -noout -out key.priv.pem
openssl ec -in key.priv.pem -pubout -out key.pub.pem 2>/dev/null || true
make || echo "WARNING: regulatory.db build had non-zero exit - checking output..."

if [ ! -f regulatory.db ]; then
    echo "!!!! regulatory.db was not produced - regdb build failed."
    exit 1
fi

mkdir -p ../openwrt/files/lib/firmware
cp regulatory.db ../openwrt/files/lib/firmware/regulatory.db
[ -f regulatory.db.p7s ] && cp regulatory.db.p7s ../openwrt/files/lib/firmware/regulatory.db.p7s
echo "Injected $(wc -c < ../openwrt/files/lib/firmware/regulatory.db) byte custom regulatory.db"
echo "✅ Regulatory database ready."
