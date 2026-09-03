#!/bin/bash
# =============================================
# Script 6: Generate Custom Unlocked Regulatory DB
# =============================================
# Runs from the repository root. Clones wireless-regdb, generates
# a db.txt that gives every country the full 5115-5930 MHz range
# at 160 MHz / 33 dBm (no DFS flag, no NO_IR), signs it, and
# drops the resulting regulatory.db into openwrt/files/ so OpenWrt
# bundles it into the squashfs instead of the stock restricted one.
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
        f.write('\t(2182 - 2494 @ 40), (33)\n')
        f.write('\t(5115 - 5930 @ 160), (33)\n')
        f.write('\n')
print('Generated db.txt with %d countries' % len(countries))
PYEOF

openssl ecparam -name prime256v1 -genkey -noout -out key.priv.pem
make || echo "WARNING: regulatory.db build had non-zero exit - checking output..."

if [ ! -f regulatory.db ]; then
    echo "!!!! regulatory.db was not produced - regdb build failed."
    exit 1
fi

mkdir -p ../openwrt/files/lib/firmware
cp regulatory.db ../openwrt/files/lib/firmware/regulatory.db
echo "Injected $(wc -c < ../openwrt/files/lib/firmware/regulatory.db) byte custom regulatory.db"
echo "✅ Regulatory database ready."
