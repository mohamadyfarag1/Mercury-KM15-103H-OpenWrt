#!/bin/sh
# Safely disable Extroot and reboot to internal NAND flash
# Mercury KM15-103H (MT7621 + USB 3.0)

echo "=========================================="
echo " Safely Ejecting USB Extroot..."
echo "=========================================="

# 1. Gracefully stop disk-writing services (Docker, Samba, etc.)
echo "Stopping background storage services..."
/etc/init.d/dockerd stop 2>/dev/null || true
/etc/init.d/samba4 stop 2>/dev/null || true
sync

# 2. Locate the internal NAND flash rootfs_data device
find_nand_dev() {
    # Method 1: Check UBI volume named rootfs_data
    for ubi in /sys/class/ubi/ubi*; do
        if [ -f "$ubi/name" ] && [ "$(cat "$ubi/name" 2>/dev/null)" = "rootfs_data" ]; then
            local b=$(basename "$ubi")
            if [ -e "/dev/$b" ]; then
                echo "/dev/$b"
                return 0
            fi
        fi
    done

    # Method 2: Standard MT7621 NAND UBI rootfs_data node
    if [ -e "/dev/ubi0_1" ]; then
        echo "/dev/ubi0_1"
        return 0
    fi

    # Method 3: MTD block partition named rootfs_data
    local mtd_num=$(grep '"rootfs_data"' /proc/mtd 2>/dev/null | cut -d: -f1 | sed 's/mtd//')
    if [ -n "$mtd_num" ] && [ -e "/dev/mtdblock$mtd_num" ]; then
        echo "/dev/mtdblock$mtd_num"
        return 0
    fi

    # Method 4: Non-USB block device with ubifs / jffs2 / f2fs
    local fb=$(block info 2>/dev/null | grep -E 'TYPE="(ubifs|jffs2|f2fs)"' | grep -v '^/dev/sd' | cut -d: -f1 | head -n 1)
    if [ -n "$fb" ]; then
        echo "$fb"
        return 0
    fi

    return 1
}

NAND_DEV=$(find_nand_dev)
if [ -n "$NAND_DEV" ]; then
    echo "Found internal NAND flash storage: $NAND_DEV"
    NAND_MNT="/tmp/nand_eject_mnt"
    mkdir -p "$NAND_MNT"

    if mount "$NAND_DEV" "$NAND_MNT" 2>/dev/null || mount -t ubifs "$NAND_DEV" "$NAND_MNT" 2>/dev/null; then
        NAND_CFG=""
        if [ -d "$NAND_MNT/upper/etc/config" ]; then
            NAND_CFG="$NAND_MNT/upper/etc/config"
        elif [ -d "$NAND_MNT/etc/config" ]; then
            NAND_CFG="$NAND_MNT/etc/config"
        fi

        if [ -n "$NAND_CFG" ]; then
            echo "Disabling fstab overlay on internal NAND flash..."
            uci -c "$NAND_CFG" set fstab.overlay.enabled="0" 2>/dev/null
            uci -c "$NAND_CFG" commit fstab 2>/dev/null
            echo "✅ NAND flash fstab updated: Extroot is disabled for next boot."
        else
            echo "⚠️ Could not locate etc/config on NAND mount."
        fi

        sync
        umount "$NAND_MNT" 2>/dev/null
        rmdir "$NAND_MNT" 2>/dev/null || true
    else
        echo "⚠️ Could not mount $NAND_DEV to update NAND fstab."
    fi
else
    echo "⚠️ Internal NAND storage device not found."
fi

# 3. Also update current active fstab for consistency
uci set fstab.overlay.enabled="0" 2>/dev/null
uci commit fstab 2>/dev/null

echo "Flushing all disk buffers..."
sync

echo "=========================================="
echo "✅ USB Extroot safely disabled!"
echo "The router will now reboot and boot ONLY into the internal NAND flash."
echo "ℹ️ You do NOT need to unplug the USB flash drive - the router will ignore it"
echo "   and boot to NAND. All files on the USB remain safely preserved."
echo "   Whenever you want to switch back to USB, use 'Re-enable Existing USB'."
echo "=========================================="
sleep 3
reboot
