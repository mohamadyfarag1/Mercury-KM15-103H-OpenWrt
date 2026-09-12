#!/bin/bash
echo ">>> Running Mercury Kernel Regdom Patch..."
cd openwrt

MAC80211_SH="package/kernel/mac80211/files/lib/netifd/wireless/mac80211.sh"
if [ -f "$MAC80211_SH" ]; then
    echo ">>> Patching mac80211.sh..."
    sed -i 's/local chan="$1"/local chan="$1"\n\t[ "$chan" -gt 1000 ] \&\& { echo "$chan"; return 0; }/g' "$MAC80211_SH"
else
    echo "ERROR: mac80211.sh not found!"
fi

mkdir -p package/kernel/mac80211/patches/
REG_PATCH="package/kernel/mac80211/patches/999-unlock-world-regdom.patch"
echo ">>> Creating world_regdom kernel patch..."
cat << 'EOF' > "$REG_PATCH"
--- a/net/wireless/reg.c
+++ b/net/wireless/reg.c
@@ -107,10 +107,10 @@
 	REG_RULE(5150, 5250, 40, 0, 20, 0),
 	REG_RULE(5250, 5350, 40, 0, 20, 0),
 	REG_RULE(5470, 5730, 40, 0, 20, 0),
-	REG_RULE(5730, 5850, 80, 0, 20, 0),
+	REG_RULE(4900, 6100, 160, 0, 33, 0),
 	/* 60 GHz band, completely open for everyone. */
 	REG_RULE(57240, 65880, 2160, 0, 40, 0),
 };
EOF
