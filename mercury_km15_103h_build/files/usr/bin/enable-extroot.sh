#!/bin/sh
# Re-enable existing USB Extroot on Mercury KM15-103H without formatting
# Preserves all installed packages, Docker containers, and data.

echo "=========================================="
echo " Checking USB Extroot Drive..."
echo "=========================================="

# 1. Check if Extroot is ALREADY active
if grep -qE '^/dev/sd[a-z][0-9]* /overlay' /proc/mounts 2>/dev/null; then
    echo "ℹ️ USB Extroot is ALREADY active and mounted as /overlay!"
    echo "Current storage is already expanded to the USB drive."
    echo "No action needed."
    exit 0
fi

# 2. Locate USB partition formatted with ext4
USB_PART=$(block info 2>/dev/null | grep 'TYPE="ext4"' | grep -oE '^/dev/sd[a-z][0-9]*' | head -n 1)
if [ -z "$USB_PART" ]; then
    USB_PART=$(block info 2>/dev/null | grep -oE '^/dev/sd[a-z][0-9]+' | head -n 1)
fi

if [ -z "$USB_PART" ]; then
    echo "❌ Error: No USB storage partition detected!"
    echo "Please insert a USB flash drive into the USB port and try again."
    exit 1
fi

FS_TYPE=$(block info "$USB_PART" 2>/dev/null | grep -oE 'TYPE="[^"]+"' | cut -d'"' -f2)
if [ "$FS_TYPE" != "ext4" ]; then
    echo "❌ ERROR: Partition $USB_PART is not ext4 (detected: $FS_TYPE)!"
    echo "Please use 'Format USB & Expand Space (Extroot)' first."
    exit 1
fi

echo "Found ext4 partition: $USB_PART"

# 3. Mount partition temporarily to verify it contains valid Extroot data
CHECK_DIR="/tmp/usb_check"
mkdir -p "$CHECK_DIR"
if ! mount "$USB_PART" "$CHECK_DIR" 2>/dev/null; then
    echo "❌ ERROR: Could not mount $USB_PART!"
    rmdir "$CHECK_DIR" 2>/dev/null
    exit 1
fi

if [ ! -d "$CHECK_DIR/upper" ] && [ ! -d "$CHECK_DIR/etc" ] && [ ! -f "$CHECK_DIR/.fs_state" ]; then
    echo "⚠️ WARNING: Partition $USB_PART is ext4 but does not appear to contain an Extroot filesystem."
    echo "Use 'Format USB & Expand Space (Extroot)' if you want to initialize it."
    umount "$CHECK_DIR" 2>/dev/null
    rmdir "$CHECK_DIR" 2>/dev/null
    exit 1
fi

echo "✅ Verified existing Extroot filesystem structure on $USB_PART."

# 4. Kernel modules compatibility check (sync new modules if kernel version changed)
CURRENT_KERNEL=$(uname -r)
TARGET_DIR="$CHECK_DIR"
[ -d "$CHECK_DIR/upper" ] && TARGET_DIR="$CHECK_DIR/upper"

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

# 5. Get UUID of the USB partition
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
echo "✅ SUCCESS! Extroot re-enabled (NO format was performed)."
echo "All your files, Docker containers, and packages are 100% intact."
echo "The router will reboot now to mount the USB drive as root storage."
echo "=========================================="
sleep 3
reboot
