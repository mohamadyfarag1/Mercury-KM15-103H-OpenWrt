#!/bin/bash
echo ">>> Running MT76 Channels Injection..."
cd openwrt

mkdir -p package/kernel/mt76/patches/
echo ">>> Copying mt76 channels patch..."
cp ../scripts/999-mt76-5ghz-superchannels.patch package/kernel/mt76/patches/
