# خريطة وتفاصيل هاردوير راوتر Mercury KM15-103H (KT GiGA WiFi home ax)

## 1. المعلومات الأساسية للجهاز (System Overview)
- **الموديل (Model):** Mercury KM15-103H
- **المعالج (SoC):** MediaTek MT7621AT (MIPS 1004Kc dual-core, 4 virtual cores @ 880 MHz)
- **الذاكرة العشوائية (RAM):** 256 MB DDR3
- **الذاكرة الفلاشية (Flash):** 128 MB SPI-NAND (`mt7621-nand`) بتقنية NMBM (NAND Multi-Block Management)
- **شريحة الواي فاي (Wi-Fi Chipset):** MediaTek MT7915E (PCIe interface)
  - **2.4 GHz:** 802.11b/g/n/ax (HE20 / HE40) - 3x3 MIMO
  - **5 GHz:** 802.11a/n/ac/ax (VHT80 / HE80) - 3x3 MIMO
- **السويتش والشبكة السلكية (Ethernet Switch):** MT7530 Switch (DSA Architecture)
  - 1 منفذ WAN جيجابت (Port 0)
  - 4 منافذ LAN جيجابت (Ports 1, 2, 3, 4)
- **نظام التشغيل الحالي:** WitWrt 24.10.2 (مبني على OpenWrt 24.10.2 - نواة Linux 6.6.93)
- **الهدف في OpenWrt (Target):** `ramips/mt7621` (Subtarget: `nand`)

---

## 2. خريطة الذاكرة والفلاش (MTD Partition Table)

حجم الفلاش الكلي: **128 ميجابايت** (NAND Flash Block size = 128 KB = 0x20000):

| اسم القسم (Name) | البداية (Offset) | الحجم (Hex) | الحجم (Bytes) | الوظيفة والمحتوى |
|---|---|---|---|---|
| **mtd0: Bootloader** | `0x00000000` | `0x00080000` | 512 KB | بوت لودر الجهاز (U-Boot) - تم سحبه بنجاح |
| **mtd1: Config** | `0x000c0000` | `0x00040000` | 256 KB | يحتوي على الماك أدرس الأصلي عند الإزاحة 0x4 |
| **mtd2: Factory** | `0x00100000` | `0x00080000` | 512 KB | بارتشن المعايرة (EEPROM + Precal) الخاص بالواي فاي MT7915 |
| **mtd3: firmware** | `0x00180000` | `0x03000000` | 48 MB | بنك الفيرموير الأساسي (FIT Image: kernel + UBI/rootfs) |
| **mtd4: kernel** | (داخل firmware) | `0x00320000` | 3.125 MB | نواة لينكس المضمنة في الـ FIT Image |
| **mtd5: ubi** | (داخل firmware) | `0x02c00000` | 44 MB | مساحة الروت والملفات (UBIFS) |
| **mtd6: firmware2** | `0x03180000` | `0x03000000` | 48 MB | بنك الفيرموير الاحتياطي (Dual-Boot Bank) |
| **mtd7: kernel** | (داخل firmware2)| `0x00320000` | 3.125 MB | نواة البنك الثاني |
| **mtd8: ubi** | (داخل firmware2)| `0x02c00000` | 44 MB | مساحة الروت للبنك الثاني |
| **mtd9: Userdata** | `0x06180000` | `0x01680000` | 22.5 MB | بيانات المستخدم الإضافية في الفلاش |

---

## 3. حقيقة ملفات ART و EEPROM في هذا الجهاز

> [!IMPORTANT]
> **ملاحظة تقنية هامة جداً:**
> أجهزة كوالكوم آثيروس (Qualcomm Atheros مثل IPQ4019 / AR9344) تستخدم قسم يُدعى **ART** (Atheros Radio Test).
> أما أجهزة **MediaTek** (مثل MT7621 + MT7915)، فإن كاليبريشن الواي فاي يُسمى **Factory / EEPROM / Precal** وليس ART!

### محتويات بارتشن Factory (mtd2):
تم سحب بارتشن `mtd2` بالكامل وتحليله هيدروبايت:
1. **ملف الـ EEPROM الخاص بـ MT7915:**
   - الإزاحة: من `0x0000` إلى `0x0E10` (الحجم: 3600 بايت).
   - الهيدر يبدأ بـ `15 79 00 00` وهو كود الشريحة MT7915.
   - يتضمن PCI IDs ومعلومات الترددات الأساسية.
2. **ملف الـ Precal (معايرة الترددات الدقيقة):**
   - الإزاحة: من `0x0E10` إلى `0x1AA20` (الحجم: 105,488 بايت).
   - هذا الملف يحتوي على مصفوفات الـ RF Calibration لموديلات MT7915 / MT7975.
3. **سبب المشاكل والخلل في السوفت الحالي:**
   - **الماك أدرس داخل الـ EEPROM:** مخزن به ماك افتراضي تجريبي من شركة ميدياتك (`00:0c:43:26:46:60`)، بينما الماك الحقيقي للجهاز مخزن في بارتشن `Config` (`0c:96:cd:9f:cb:19`).
   - **حدود الباور (Tx-Power Limits):** الفيرموير الحالي يضع قيوداً قوية على قدرة البث (20 dBm) ويقفل القنوات 12 و 13 و 14 في تردد 2.4 جيجا، والقنوات العالية مقيدة.
   - **سوفت WitWrt:** نظام مغلق خاص بشركات ومزودات خدمة (ISPs) يحتوي على خدمات سحابية وقفل قيود، ومعدل لتتبع ومراقبة الأجهزة.

---

## 4. عناوين الماك (MAC Addresses Architecture)
- **Base MAC (في بارتشن Config عند 0x4):** `0c:96:cd:9f:cb:19`
- **WAN MAC:** `0c:96:cd:9f:cb:19` (Base MAC + 0)
- **LAN MAC:** `0c:96:cd:9f:cb:1a` (Base MAC + 1)
- **Wi-Fi 2.4 GHz MAC:** `0c:96:cd:9f:cb:1b` (Base MAC + 2)
- **Wi-Fi 5 GHz MAC:** `0c:96:cd:9f:cb:1c` (Base MAC + 3)

---

## 5. خريطة منافذ الـ GPIO والأزرار والليدات (LEDs & Keys)

### الأزرار (Buttons):
- **Reset Button:** GPIO 3 (Active Low)
- **WPS Button:** GPIO 4 (Active Low)
- **LED Switch:** GPIO 6 (Active Low)

### الليدات (LEDs):
- **WLAN 2.4G Green:** GPIO 13 (mt7621-gpio)
- **LAN 2 Green:** GPIO 14 (mt7621-gpio)
- **LAN 1 Green:** Switch GPIO 12
- **LAN 3 Green:** Switch GPIO 6
- **LAN 4 Green:** Switch GPIO 3
- **WAN Green:** Switch GPIO 0
- **SYS Blue:** Switch GPIO 9

---

## 6. الملفات المسحوبة والمحفوظة في مجلد `KM15-103H_Backup`
1. `mtd0_Bootloader.bin` (الـ U-Boot الأصلي للجهاز - 512KB)
2. `mtd1_Config.bin` (ملف الكونفيج والماك أدرس الأصلي - 256KB)
3. `mtd2_Factory.bin` (ملف الفاكتوري الكامل - 512KB)
4. `mt7915_eeprom.bin` (ملف إيبروم الشريحة مفصولاً بدقة - 3600 بايت)
5. `mt7915_precal.bin` (ملف الكاليبريشن المنفصل - 105,488 بايت)
6. `device_tree.dtb` (ملف الـ DTB الثنائي المستخرج مباشرة من الرام ونواة الجهاز)
7. `mercury_km15_103h.dts` (ملف شجرة العتاد الكامل DTS جاهز للبناء والدمج المباشر في OpenWrt)
8. ملفات تشخيص كاملة للشبكة والسويتش والواي فاي والـ dmesg.
