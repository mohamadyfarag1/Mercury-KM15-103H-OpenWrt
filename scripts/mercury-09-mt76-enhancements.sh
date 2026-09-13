#!/bin/bash
echo ">>> Applying MT7915 Tx-Power and Data Rate Enhancements..."

# 1. Update MT7915 Firmware blobs to latest from Linux-Firmware upstream
mkdir -p openwrt/files/lib/firmware/mediatek
echo "Downloading latest MT7915 firmware blobs..."
wget -qO openwrt/files/lib/firmware/mediatek/mt7915_wa.bin "https://git.kernel.org/pub/scm/linux/kernel/git/firmware/linux-firmware.git/plain/mediatek/mt7915_wa.bin"
wget -qO openwrt/files/lib/firmware/mediatek/mt7915_wm.bin "https://git.kernel.org/pub/scm/linux/kernel/git/firmware/linux-firmware.git/plain/mediatek/mt7915_wm.bin"
wget -qO openwrt/files/lib/firmware/mediatek/mt7915_rom_patch.bin "https://git.kernel.org/pub/scm/linux/kernel/git/firmware/linux-firmware.git/plain/mediatek/mt7915_rom_patch.bin"
chmod 644 openwrt/files/lib/firmware/mediatek/mt7915*.bin

# 2. Patch mac80211 MT76 driver to bypass EEPROM Tx-Power limits (force 30 dBm)
mkdir -p openwrt/package/kernel/mac80211/patches/mediatek
cat << 'EOF' > openwrt/package/kernel/mac80211/patches/mediatek/999-mt7915-force-30dbm-txpower.patch
--- a/drivers/net/wireless/mediatek/mt76/mt7915/eeprom.c
+++ b/drivers/net/wireless/mediatek/mt76/mt7915/eeprom.c
@@ -101,6 +101,11 @@ static void mt7915_eeprom_parse_hw_cap(s
 	if (phy->mt76->band_ext)
 		phy->mt76->tx_power_limit = 24 * 2;
 
+	/* HORUS OVERRIDE: Force 30 dBm (60 half-dBm) maximum Tx-Power limit for both bands */
+	phy->mt76->tx_power_limit = 60;
+	phy->mt76->antenna_gain = 0;
+	dev_info(dev->mt76.dev, "Horus: Forced Tx-Power limit to 30 dBm for MT7915");
+
 	mt76_eeprom_parse_mac(phy->mt76);
 	mt76_eeprom_parse_country_ie(phy->mt76);
 }
--- a/drivers/net/wireless/mediatek/mt76/mt7915/mac.c
+++ b/drivers/net/wireless/mediatek/mt76/mt7915/mac.c
@@ -1550,6 +1550,9 @@ int mt7915_mac_set_txpower(struct mt7915_dev *dev, struct mt7915_phy *phy,
 	if (txpwr_limit < 0)
 		txpwr_limit = 0;
 
+	/* HORUS OVERRIDE: Allow absolute maximum Tx-Power up to 30 dBm */
+	txpwr_limit = 60;
+
 	phy->mt76->txpwr_limit = txpwr_limit;
 
 	return mt7915_mcu_set_txpower(phy, txpwr_limit, 0);
EOF

echo ">>> MT7915 Enhancements applied successfully!"
