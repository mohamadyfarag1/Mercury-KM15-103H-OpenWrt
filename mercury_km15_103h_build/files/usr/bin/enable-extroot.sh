#!/bin/sh
# Re-enable existing USB Extroot on Mercury KM15-103H without formatting

echo "=========================================="
echo " Checking USB Extroot Drive..."
echo "=========================================="

USB_PART=$(block info | grep -oE '^/dev/sd[a-z][0-9]+' | head -n 1)
if [ -z "$USB_PART" ]; then
    echo "❌ Error: No USB storage partition detected!"
    exit 1
fi

FS_TYPE=$(block info "$USB_PART" 2>/dev/null | grep -oE 'TYPE="[^"]+"' | cut -d'"' -f2)

if [ "$FS_TYPE" != "ext4" ]; then
    echo "❌ ERROR: Partition $USB_PART is not ext4 (detected: $FS_TYPE)!"
    echo "Please use 'Format USB & Expand Space (Extroot)' first."
    exit 1
fi

echo "Found ext4 partition: $USB_PART"

# Check and sync kernel modules if kernel version changed
CHECK_DIR="/tmp/usb_check"
mkdir -p "$CHECK_DIR"
mount "$USB_PART" "$CHECK_DIR" 2>/dev/null

CURRENT_KERNEL=$(uname -r)
TARGET_DIR="$CHECK_DIR"
if [ -d "$CHECK_DIR/upper" ]; then
    TARGET_DIR="$CHECK_DIR/upper"
fi

if [ -d "$TARGET_DIR/lib/modules" ]; then
    if [ ! -d "$TARGET_DIR/lib/modules/$CURRENT_KERNEL" ]; then
        echo "⚠️ Kernel version changed ($CURRENT_KERNEL). Syncing modules to USB..."
        mkdir -p "$TARGET_DIR/lib/modules/$CURRENT_KERNEL"
        cp -a /lib/modules/$CURRENT_KERNEL/* "$TARGET_DIR/lib/modules/$CURRENT_KERNEL/" 2>/dev/null || true
    fi
fi
sync
umount "$CHECK_DIR" 2>/dev/null
rmdir "$CHECK_DIR" 2>/dev/null || true

# Get UUID
UUID=$(block info "$USB_PART" 2>/dev/null | grep -o -e 'UUID="[^"]*"' | cut -d'"' -f2)
if [ -z "$UUID" ]; then
    UUID=$(block info "$USB_PART" 2>/dev/null | grep -o -e 'UUID=\S*' | cut -d'=' -f2 | tr -d '"')
fi

if [ -z "$UUID" ]; then
    echo "❌ ERROR: Could not read UUID for $USB_PART!"
    exit 1
fi

echo "Re-enabling Extroot with UUID: $UUID"
uci -q delete fstab.overlay
uci set fstab.overlay="mount"
uci set fstab.overlay.uuid="${UUID}"
uci set fstab.overlay.target="/overlay"
uci set fstab.overlay.enabled="1"
uci commit fstab
sync

echo "=========================================="
echo "✅ Done! Router will reboot to boot from USB."
echo "=========================================="
sleep 3
reboot
