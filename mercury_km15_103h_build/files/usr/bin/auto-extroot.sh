#!/bin/sh
# Auto-Extroot Script for Mercury KM15-103H (MT7621 + USB 3.0)
# Automatically partitions, formats, and migrates /overlay to USB drive

echo "=========================================="
echo " Starting Auto-Extroot (Storage Expansion)"
echo "=========================================="

DEVICE=$(ls /dev/sd[a-z] 2>/dev/null | head -n 1)

if [ -z "$DEVICE" ] || [ ! -b "$DEVICE" ]; then
    echo "❌ ERROR: No USB drive detected!"
    echo "Please insert a USB flash drive into the USB port and try again."
    exit 1
fi

echo "Found USB drive: $DEVICE"
echo "⚠️ WARNING: This will format and erase ALL data on $DEVICE!"

# Unmount any currently mounted partitions on this device
echo "Unmounting existing partitions on $DEVICE..."
for part in $(ls ${DEVICE}* 2>/dev/null); do
    umount "$part" 2>/dev/null || true
    swapoff "$part" 2>/dev/null || true
done
sleep 1

# Create a single primary MBR partition spanning 100% of the drive
echo "Partitioning $DEVICE..."
printf "o\nn\np\n1\n\n\nw\n" | fdisk "$DEVICE" >/dev/null 2>&1
sleep 2

# Wait for kernel to register partition
PARTITION="${DEVICE}1"
if [ ! -b "$PARTITION" ]; then
    # Some kernels name it differently or need partprobe
    sleep 2
    PARTITION=$(ls ${DEVICE}[0-9]* 2>/dev/null | head -n 1)
fi

if [ -z "$PARTITION" ] || [ ! -b "$PARTITION" ]; then
    echo "❌ ERROR: Failed to create partition on $DEVICE!"
    exit 1
fi

echo "Created partition: $PARTITION"

# Format to ext4 with journaling
echo "Formatting $PARTITION to ext4..."
mkfs.ext4 -F "$PARTITION"

if [ $? -ne 0 ]; then
    echo "❌ ERROR: Formatting $PARTITION failed!"
    exit 1
fi

echo "✅ Format complete."

# Get UUID of the new ext4 partition
UUID=$(block info "$PARTITION" 2>/dev/null | grep -o -e 'UUID="[^"]*"' | cut -d'"' -f2)
if [ -z "$UUID" ]; then
    UUID=$(block info "$PARTITION" 2>/dev/null | grep -o -e 'UUID=\S*' | cut -d'=' -f2 | tr -d '"')
fi

if [ -z "$UUID" ]; then
    echo "❌ ERROR: Could not retrieve UUID for $PARTITION!"
    exit 1
fi

echo "Partition UUID: $UUID"

# Configure UCI fstab for Extroot on internal NAND
echo "Configuring fstab for Extroot (/overlay mount)..."
uci -q delete fstab.overlay
uci set fstab.overlay="mount"
uci set fstab.overlay.uuid="${UUID}"
uci set fstab.overlay.target="/overlay"
uci set fstab.overlay.enabled="1"
uci commit fstab
sync

# Mount and copy current overlay data
MOUNT_DIR="/tmp/extroot_mnt"
mkdir -p "$MOUNT_DIR"
mount "$PARTITION" "$MOUNT_DIR"

if [ $? -ne 0 ]; then
    echo "❌ ERROR: Could not mount $PARTITION to $MOUNT_DIR!"
    exit 1
fi

echo "Copying system configuration and installed packages from /overlay..."
tar -C /overlay -cf - . | tar -C "$MOUNT_DIR" -xf -
sync
umount "$MOUNT_DIR"
rmdir "$MOUNT_DIR" 2>/dev/null || true

echo "=========================================="
echo "✅ SUCCESS! Extroot is configured."
echo "The router will reboot now to mount the USB drive as root storage."
echo "After reboot, your storage will be expanded to the full size of the USB drive!"
echo "=========================================="
sleep 4
reboot
