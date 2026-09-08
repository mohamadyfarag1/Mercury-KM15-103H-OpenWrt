#!/bin/sh
# Safely disable Extroot and reboot to internal NAND flash

echo "=========================================="
echo " Safely Ejecting USB Extroot..."
echo "=========================================="

echo "Flushing disk caches to USB..."
sync

# Disable fstab overlay so next boot mounts internal NAND flash
echo "Disabling fstab overlay mount..."
uci set fstab.overlay.enabled="0" 2>/dev/null
uci commit fstab 2>/dev/null
sync

echo "Disk buffers flushed successfully."
echo "The router will now reboot into the internal NAND flash."
echo "⚠️ DO NOT unplug the USB drive yet - it is still mounted until the reboot completes."
echo "Wait until the router has finished rebooting, THEN unplug the USB drive."
echo "=========================================="
sleep 3
reboot
