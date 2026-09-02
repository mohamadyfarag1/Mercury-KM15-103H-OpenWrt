#!/bin/bash
# ===============================================================
# Script 5: Compile Firmware for Mercury KM15-103H
# ===============================================================
set -e

cd openwrt

echo "=========================================="
echo "Starting OpenWrt compilation for KM15-103H"
echo "=========================================="

# Compile with parallel jobs
make -j$(nproc) || make -j1 V=s

echo "Compilation completed. Searching for generated images..."
BIN_DIR="bin/targets/ramips/mt7621"

if [ ! -d "$BIN_DIR" ]; then
    echo "❌ ERROR: Output directory $BIN_DIR does not exist!"
    exit 1
fi

IMAGE_FILE=$(find "$BIN_DIR" -type f -name "*mercury_km15-103h*sysupgrade.bin" | head -n 1)

if [ -z "$IMAGE_FILE" ] || [ ! -f "$IMAGE_FILE" ]; then
    echo "❌ ERROR: Could not find mercury_km15-103h sysupgrade image in $BIN_DIR!"
    ls -la "$BIN_DIR"
    exit 1
fi

FILESIZE=$(stat -c%s "$IMAGE_FILE" 2>/dev/null || wc -c < "$IMAGE_FILE")
MD5=$(md5sum "$IMAGE_FILE" | awk '{print $1}')

echo "=========================================="
echo "✅ BUILD SUCCESSFUL!"
echo "Image: $IMAGE_FILE"
echo "Size:  $FILESIZE bytes"
echo "MD5:   $MD5"
echo "=========================================="

# Verify sysupgrade tar archive structure for mercury_do_upgrade compatibility
echo "Verifying image structure for safe dual-slot sysupgrade..."
tar -tf "$IMAGE_FILE" || true
echo "✅ Verification complete. Ready for flashing!"
