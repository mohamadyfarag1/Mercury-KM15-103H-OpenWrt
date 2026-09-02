#!/bin/sh
#
# Copyright (C) 2025 WitWrt.com
#

. /lib/functions.sh

RAMFS_COPY_BIN='nandwrite flash_erase hexdump'

MERCURY_DATA_PART="Userdata"
MERCURY_DATA_VOLUME="priv_data"
MERCURY_DATA_MOUNT="/tmp/priv_data"

mercury_get_mtd_num() {
	local part_name="$1"
	local mtd_line mtd_num

	mtd_line=$(grep "\"${part_name}\"" /proc/mtd 2>/dev/null | sed -n '1p')
	if [ -z "$mtd_line" ]; then
		return 1
	fi

	mtd_num=$(echo "$mtd_line" | sed -n 's/^mtd\([0-9]*\):.*$/\1/p')
	if [ -z "$mtd_num" ]; then
		return 1
	fi

	echo "$mtd_num"
	return 0
}

mercury_mount_data() {
	local data_mtd_num data_mtd_dev

	data_mtd_num=$(mercury_get_mtd_num "${MERCURY_DATA_PART}")
	if [ -z "$data_mtd_num" ]; then
		echo "Mercury: WARNING - Data partition '$MERCURY_DATA_PART' not found"
		return 1
	fi
	data_mtd_dev="/dev/mtd${data_mtd_num}"
	echo "Mercury: Data partition: $data_mtd_dev (mtd$data_mtd_num)"

	local ubi_num=""
	local ubi_dev
	for ubi_dev in /sys/class/ubi/ubi[0-9]*; do
		[ -d "$ubi_dev" ] || continue
		local mtd_num="$(cat "$ubi_dev/mtd_num" 2>/dev/null)"
		if [ "$mtd_num" = "$data_mtd_num" ]; then
			ubi_num="$(basename "$ubi_dev")"
			ubi_num="${ubi_num#ubi}"
			break
		fi
	done

	if [ -z "$ubi_num" ]; then
		echo "Mercury: Attaching UBI to data partition (mtd$data_mtd_num)..."
		if ! ubiattach -m "$data_mtd_num" 2>/dev/null; then
			echo "Mercury: UBI not formatted, formatting data partition..."
			ubiformat -y "$data_mtd_dev" 2>/dev/null
			if ! ubiattach -m "$data_mtd_num" 2>/dev/null; then
				echo "Mercury: ERROR - Failed to attach UBI to data partition"
				return 1
			fi
		fi

		for ubi_dev in /sys/class/ubi/ubi[0-9]*; do
			[ -d "$ubi_dev" ] || continue
			local mtd_num="$(cat "$ubi_dev/mtd_num" 2>/dev/null)"
			if [ "$mtd_num" = "$data_mtd_num" ]; then
				ubi_num="$(basename "$ubi_dev")"
				ubi_num="${ubi_num#ubi}"
				break
			fi
		done
	fi

	if [ -z "$ubi_num" ]; then
		echo "Mercury: ERROR - Cannot find UBI device for data partition"
		return 1
	fi
	echo "Mercury: Using UBI device: ubi$ubi_num"

	if ! ubinfo -d "$ubi_num" -N "$MERCURY_DATA_VOLUME" >/dev/null 2>&1; then
		echo "Mercury: Creating $MERCURY_DATA_VOLUME volume..."
		if ! ubimkvol "/dev/ubi$ubi_num" -N "$MERCURY_DATA_VOLUME" -m; then
			echo "Mercury: ERROR - Failed to create priv_data volume"
			return 1
		fi
	fi

	mkdir -p "$MERCURY_DATA_MOUNT"
	if ! mount -t ubifs "ubi$ubi_num:$MERCURY_DATA_VOLUME" "$MERCURY_DATA_MOUNT" 2>/dev/null; then
		echo "Mercury: ERROR - Failed to mount priv_data volume"
		return 1
	fi

	echo "Mercury: Data partition mounted at $MERCURY_DATA_MOUNT"
	return 0
}

mercury_umount_data() {
	umount "$MERCURY_DATA_MOUNT" 2>/dev/null
	rm -rf "$MERCURY_DATA_MOUNT"
}

mercury_save_config() {
	local config_file="$1"

	if ! mercury_mount_data; then
		echo "Mercury: WARNING - Cannot save config, data partition unavailable"
		return 1
	fi

	if [ -z "$config_file" ] || [ ! -f "$config_file" ]; then
		echo "Mercury: Generating configuration backup..."
		config_file="/tmp/sysupgrade.tgz"
		sysupgrade --create-backup "$config_file" 2>/dev/null
		if [ ! -f "$config_file" ]; then
			echo "Mercury: ERROR - Failed to generate configuration backup"
			mercury_umount_data
			return 1
		fi
	fi

	echo "Mercury: Saving configuration to priv_data volume..."
	if ! cp "$config_file" "$MERCURY_DATA_MOUNT/sysupgrade.tgz"; then
		echo "Mercury: ERROR - Failed to save configuration"
		mercury_umount_data
		return 1
	fi

	sync
	mercury_umount_data
	echo "Mercury: Configuration saved successfully"
	return 0
}

mercury_switch_boot_slot() {
	local config_mtd="$1"
	local target_slot="$2"
	local backup_file="/tmp/config_backup.bin"
	local modified_file="/tmp/config_modified.bin"
	local verify_byte

	echo "Mercury: Switching boot slot to $target_slot"

	echo "Mercury: Backing up Config partition..."
	dd if="$config_mtd" of="$backup_file" bs=64k 2>/dev/null
	if [ ! -f "$backup_file" ]; then
		echo "Mercury: ERROR - Failed to backup Config partition"
		return 1
	fi

	cp "$backup_file" "$modified_file"
	if [ ! -f "$modified_file" ]; then
		echo "Mercury: ERROR - Failed to create working copy"
		rm -f "$backup_file"
		return 1
	fi

	printf "\\x0${target_slot}" | dd of="$modified_file" bs=1 seek=10 count=1 conv=notrunc 2>/dev/null

	printf "\\x0${target_slot}" | dd of="$modified_file" bs=1 seek=131082 count=1 conv=notrunc 2>/dev/null

	verify_byte=$(dd if="$modified_file" bs=1 skip=10 count=1 2>/dev/null | hexdump -e '"%d"')
	if [ "$verify_byte" != "$target_slot" ]; then
		echo "Mercury: ERROR - RAM modification verification failed at 0xA (expected $target_slot, got $verify_byte)"
		rm -f "$backup_file" "$modified_file"
		return 1
	fi
	echo "Mercury: RAM verification passed at 0xA (slot=$verify_byte)"

	verify_byte=$(dd if="$modified_file" bs=1 skip=131082 count=1 2>/dev/null | hexdump -e '"%d"')
	if [ "$verify_byte" != "$target_slot" ]; then
		echo "Mercury: ERROR - RAM modification verification failed at 0x2000A (expected $target_slot, got $verify_byte)"
		rm -f "$backup_file" "$modified_file"
		return 1
	fi
	echo "Mercury: RAM verification passed at 0x2000A (slot=$verify_byte)"

	echo "Mercury: Erasing Config partition..."
	if ! flash_erase "$config_mtd" 0 0 2>/dev/null; then
		echo "Mercury: ERROR - Failed to erase Config partition"
		rm -f "$backup_file" "$modified_file"
		return 1
	fi

	echo "Mercury: Writing modified Config partition..."
	if ! dd if="$modified_file" of="$config_mtd" bs=64k 2>/dev/null; then
		echo "Mercury: ERROR - Failed to write Config partition"
		echo "Mercury: CRITICAL - Attempting recovery from backup..."
		flash_erase "$config_mtd" 0 0 2>/dev/null
		dd if="$backup_file" of="$config_mtd" bs=64k 2>/dev/null
		rm -f "$backup_file" "$modified_file"
		return 1
	fi

	verify_byte=$(dd if="$config_mtd" bs=1 skip=10 count=1 2>/dev/null | hexdump -e '"%d"')
	if [ "$verify_byte" != "$target_slot" ]; then
		echo "Mercury: ERROR - Flash verification failed at 0xA (expected $target_slot, got $verify_byte)"
		echo "Mercury: CRITICAL - Attempting recovery from backup..."
		flash_erase "$config_mtd" 0 0 2>/dev/null
		dd if="$backup_file" of="$config_mtd" bs=64k 2>/dev/null
		rm -f "$backup_file" "$modified_file"
		return 1
	fi
	echo "Mercury: Flash verification passed at 0xA (slot=$verify_byte)"

	verify_byte=$(dd if="$config_mtd" bs=1 skip=131082 count=1 2>/dev/null | hexdump -e '"%d"')
	if [ "$verify_byte" != "$target_slot" ]; then
		echo "Mercury: ERROR - Flash verification failed at 0x2000A (expected $target_slot, got $verify_byte)"
		echo "Mercury: CRITICAL - Attempting recovery from backup..."
		flash_erase "$config_mtd" 0 0 2>/dev/null
		dd if="$backup_file" of="$config_mtd" bs=64k 2>/dev/null
		rm -f "$backup_file" "$modified_file"
		return 1
	fi
	echo "Mercury: Flash verification passed at 0x2000A (slot=$verify_byte)"

	echo "Mercury: Boot slot switched to $target_slot (both positions verified)"

	rm -f "$backup_file" "$modified_file"
	return 0
}

mercury_do_upgrade() {
	local config_mtd config_mtd_num target_mtd target_mtd_num current_slot target_slot target_part
	local image_file="$1"
	local preserve_config="${UPGRADE_BACKUP:+1}"

	echo "Mercury: Starting firmware upgrade..."

	config_mtd_num=$(mercury_get_mtd_num "Config")
	if [ -z "$config_mtd_num" ]; then
		echo "Mercury: ERROR - Config partition not found"
		return 1
	fi
	config_mtd="/dev/mtd${config_mtd_num}"
	echo "Mercury: Config MTD: $config_mtd (mtd$config_mtd_num)"

	current_slot=$(dd if="$config_mtd" bs=1 skip=10 count=1 2>/dev/null | hexdump -e '"%d"')
	echo "Mercury: Current boot slot: $current_slot"

	case "$current_slot" in
		1) target_slot=2; target_part="firmware2" ;;
		*) target_slot=1; target_part="firmware" ;;
	esac
	echo "Mercury: Target slot: $target_slot ($target_part)"

	target_mtd_num=$(mercury_get_mtd_num "${target_part}")
	if [ -z "$target_mtd_num" ]; then
		echo "Mercury: ERROR - Target partition '$target_part' not found"
		return 1
	fi
	target_mtd="/dev/mtd${target_mtd_num}"
	echo "Mercury: Target MTD: $target_mtd (mtd$target_mtd_num)"

	if [ ! -f "$image_file" ]; then
		echo "Mercury: ERROR - Image file not found: $image_file"
		return 1
	fi

	if [ -n "$preserve_config" ]; then
		echo "Mercury: Preserve configuration enabled"
		mercury_save_config "$UPGRADE_BACKUP"
	else
		echo "Mercury: Preserve configuration disabled (clean install)"
	fi

	local fw_image="$image_file"
	local kernel_path
	if tar -tf "$image_file" >/dev/null 2>&1; then
		echo "Mercury: Detected sysupgrade tar format, extracting..."
		fw_image="/tmp/firmware.bin"
		kernel_path="$(tar -tf "$image_file" | grep '/kernel$' | sed -n '1p')"
		if [ -z "$kernel_path" ]; then
			echo "Mercury: ERROR - No kernel found in sysupgrade tar"
			return 1
		fi
		tar -xOf "$image_file" "$kernel_path" > "$fw_image" 2>/dev/null
		if [ ! -s "$fw_image" ]; then
			echo "Mercury: ERROR - Failed to extract firmware from sysupgrade tar"
			rm -f "$fw_image"
			return 1
		fi
		echo "Mercury: Extracted firmware from: $kernel_path"
	fi

	local fw_size=$(stat -c%s "$fw_image" 2>/dev/null || wc -c < "$fw_image")
	echo "Mercury: Firmware image size: $fw_size bytes"
	if [ "$fw_size" -lt 1000000 ]; then
		echo "Mercury: ERROR - Firmware image too small (corrupt?)"
		[ "$fw_image" != "$image_file" ] && rm -f "$fw_image"
		return 1
	fi

	echo "Mercury: Erasing target partition $target_mtd..."
	if ! flash_erase "$target_mtd" 0 0; then
		echo "Mercury: ERROR - Failed to erase target partition"
		[ "$fw_image" != "$image_file" ] && rm -f "$fw_image"
		return 1
	fi

	echo "Mercury: Writing firmware to $target_mtd..."
	if ! nandwrite -p "$target_mtd" "$fw_image"; then
		echo "Mercury: ERROR - Failed to write firmware"
		[ "$fw_image" != "$image_file" ] && rm -f "$fw_image"
		return 1
	fi
	echo "Mercury: Firmware write completed"

	[ "$fw_image" != "$image_file" ] && rm -f "$fw_image"

	if ! mercury_switch_boot_slot "$config_mtd" "$target_slot"; then
		echo "Mercury: ERROR - Failed to switch boot slot"
		echo "Mercury: WARNING - Firmware written but boot slot not switched!"
		return 1
	fi

	echo "Mercury: Upgrade complete! Rebooting to slot $target_slot..."
	sync
	reboot -f
}
