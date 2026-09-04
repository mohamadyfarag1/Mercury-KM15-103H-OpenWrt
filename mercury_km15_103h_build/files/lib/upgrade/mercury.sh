#!/bin/sh
#
# Copyright (C) 2025 WitWrt.com
#

. /lib/functions.sh

# mercury_mount_data() (used by BOTH config backup and the new rootfs
# backup/restore below) needs ubiattach/ubiformat/ubimkvol/ubinfo to set
# up the priv_data volume, and mercury_backup_rootfs/restore_rootfs need
# ubiupdatevol. All of these are separate mtd-utils binaries, not
# busybox applets, so they must be listed here explicitly or they are
# simply absent from the ramdisk stage2 runs in.
RAMFS_COPY_BIN='hexdump ubiattach ubidetach ubiupdatevol ubiformat ubimkvol ubinfo'

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

# ---------------------------------------------------------------------
# UBI rootfs handling.
#
# This device's two firmware banks ("firmware" containers at mtd3 and
# mtd6) each nominally have their OWN "kernel" and "ubi" sub-partitions
# (mtd4/mtd5 for bank 1, mtd7/mtd8 for bank 2). It LOOKS like a full A/B
# scheme, but it is not: both "ubi" sub-partitions are literally named
# "ubi" in /proc/mtd, and the kernel's UBI auto-attach picks the FIRST
# match - which is always mtd5, regardless of which bank's kernel is
# currently running. Confirmed empirically on real hardware
# (2026-09-03): booting with the Config-partition slot byte set to 2
# (bank 2's kernel loads and runs - U-Boot prints "BOOT SIDE = 2" and
# the FIT hash checks pass) still shows "ubi0: attached mtd5" in dmesg.
#
# So there is really only ONE rootfs UBI volume in practice: whichever
# ubi0 auto-attach finds (mtd5). Only the KERNEL is genuinely dual-bank;
# the rootfs is shared. mercury_do_upgrade() must therefore update THIS
# volume on every upgrade regardless of which bank it targets for the
# kernel - writing a new rootfs to the target bank's OWN "ubi"
# sub-partition (mtd8 when targeting bank 2) would be silently ignored,
# since nothing ever attaches it.
#
# The obvious risk: if the rootfs is shared, "switching back to the
# previous slot" (what the failsafe does on a bad boot) reverts the
# KERNEL but, without the backup/restore pair here, would leave the
# OLD kernel running against the NEW (just-written) rootfs - the exact
# same kind of kernel/rootfs mismatch this whole mechanism exists to
# prevent, just introduced by the revert path instead of the upgrade.
# mercury_backup_rootfs()/mercury_restore_rootfs() keep kernel and
# rootfs moving as a matched pair in both directions.
# ---------------------------------------------------------------------

MERCURY_ROOTFS_BACKUP="rootfs_backup.bin"

mercury_find_ubi_rootfs_dev() {
	local ubi_dev vol_dev
	for ubi_dev in /sys/class/ubi/ubi[0-9]*; do
		[ -d "$ubi_dev" ] || continue
		for vol_dev in "$ubi_dev"/ubi*_*; do
			[ -d "$vol_dev" ] || continue
			if [ "$(cat "$vol_dev/name" 2>/dev/null)" = "rootfs" ]; then
				echo "/dev/$(basename "$vol_dev")"
				return 0
			fi
		done
	done
	return 1
}

mercury_ubi_vol_size() {
	# Bytes, from the "rootfs" volume's own /sys attribute - not an
	# estimate: this is exactly how many bytes ubiupdatevol will read
	# back out, so the backup and the live volume can never disagree
	# on size.
	local dev="$1"
	cat "/sys/class/ubi/$(basename "$dev")/data_bytes" 2>/dev/null
}

mercury_backup_rootfs() {
	# Copies the CURRENTLY RUNNING rootfs (whatever is in the shared
	# UBI "rootfs" volume right now, known-good since it is what booted
	# this session) into priv_data, before it gets overwritten. This is
	# what mercury_restore_rootfs() plays back if the new kernel+rootfs
	# pair does not come up healthy.
	local ubi_dev size

	ubi_dev=$(mercury_find_ubi_rootfs_dev)
	if [ -z "$ubi_dev" ]; then
		echo "Mercury: ERROR - could not find the 'rootfs' UBI volume"
		return 1
	fi

	size=$(mercury_ubi_vol_size "$ubi_dev")
	if [ -z "$size" ] || [ "$size" -le 0 ]; then
		echo "Mercury: ERROR - could not read size of $ubi_dev"
		return 1
	fi

	if ! mercury_mount_data; then
		echo "Mercury: ERROR - priv_data unavailable, cannot back up rootfs"
		return 1
	fi

	echo "Mercury: Backing up current rootfs ($ubi_dev, $size bytes) before upgrade..."
	if ! dd if="$ubi_dev" of="$MERCURY_DATA_MOUNT/$MERCURY_ROOTFS_BACKUP" bs=64k 2>/dev/null; then
		echo "Mercury: ERROR - failed to back up current rootfs"
		mercury_umount_data
		return 1
	fi

	local have_size
	have_size=$(stat -c%s "$MERCURY_DATA_MOUNT/$MERCURY_ROOTFS_BACKUP" 2>/dev/null || \
	            wc -c < "$MERCURY_DATA_MOUNT/$MERCURY_ROOTFS_BACKUP")
	mercury_umount_data

	if [ "$have_size" != "$size" ]; then
		echo "Mercury: ERROR - rootfs backup size mismatch (wrote $have_size, wanted $size)"
		return 1
	fi
	echo "Mercury: Rootfs backup complete ($have_size bytes)."
	return 0
}

mercury_restore_rootfs() {
	# Used by the failsafe revert path (95mercuryfailsafe) to put the
	# OLD rootfs back so it is paired with the OLD kernel again, exactly
	# as it was before the upgrade attempt.
	local ubi_dev

	if ! mercury_mount_data; then
		echo "Mercury: WARNING - priv_data unavailable, cannot restore rootfs backup"
		return 1
	fi

	if [ ! -f "$MERCURY_DATA_MOUNT/$MERCURY_ROOTFS_BACKUP" ]; then
		echo "Mercury: no rootfs backup present, nothing to restore"
		mercury_umount_data
		return 0
	fi

	ubi_dev=$(mercury_find_ubi_rootfs_dev)
	if [ -z "$ubi_dev" ]; then
		echo "Mercury: ERROR - could not find the 'rootfs' UBI volume to restore onto"
		mercury_umount_data
		return 1
	fi

	local size
	size=$(stat -c%s "$MERCURY_DATA_MOUNT/$MERCURY_ROOTFS_BACKUP" 2>/dev/null || \
	       wc -c < "$MERCURY_DATA_MOUNT/$MERCURY_ROOTFS_BACKUP")
	echo "Mercury-Failsafe: restoring pre-upgrade rootfs onto $ubi_dev ($size bytes)..."
	if ! ubiupdatevol "$ubi_dev" "$MERCURY_DATA_MOUNT/$MERCURY_ROOTFS_BACKUP"; then
		echo "Mercury: ERROR - ubiupdatevol failed while restoring rootfs backup"
		mercury_umount_data
		return 1
	fi

	rm -f "$MERCURY_DATA_MOUNT/$MERCURY_ROOTFS_BACKUP"
	sync
	mercury_umount_data
	echo "Mercury-Failsafe: rootfs restored."
	return 0
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
	if ! mtd erase "$config_mtd" 2>/dev/null; then
		echo "Mercury: ERROR - Failed to erase Config partition"
		rm -f "$backup_file" "$modified_file"
		return 1
	fi

	echo "Mercury: Writing modified Config partition..."
	if ! dd if="$modified_file" of="$config_mtd" bs=64k 2>/dev/null; then
		echo "Mercury: ERROR - Failed to write Config partition"
		echo "Mercury: CRITICAL - Attempting recovery from backup..."
		mtd erase "$config_mtd" 2>/dev/null
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
		mtd erase "$config_mtd" 2>/dev/null
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

	# Single-bank detection: if firmware2 does not exist in /proc/mtd
	# (e.g. the DTS was built without it), override to always use the
	# single "firmware" partition and always set Config slot to 1.
	# This is safe: U-Boot still reads BOOT SIDE from Config, so slot 1
	# always boots the only bank.  If that bank ever fails, recovery
	# is via UART (CE# short) — acceptable for the extra ~44 MB of
	# rootfs space gained by dropping the second bank.
	if ! mercury_get_mtd_num "firmware2" >/dev/null 2>&1; then
		echo "Mercury: No 'firmware2' partition found - single-bank mode."
		target_slot=1
		target_part="firmware"
	fi
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

	# ------------------------------------------------------------
	# Back up the CURRENT (known-good, currently booted) rootfs before
	# touching anything. Only the kernel is truly per-bank on this
	# device - see the comment above mercury_find_ubi_rootfs_dev(). On
	# a SUBSEQUENT upgrade the backup is mandatory: without it, a bad
	# new boot would leave the old kernel running against the new rootfs
	# (a mismatch the failsafe cannot fix without the backup).
	#
	# FIRST INSTALL exception: if no "rootfs" UBI volume exists yet
	# (the "ubi" sub-partition has never been formatted), there is
	# nothing to back up. We detect this by probing for the volume
	# before attempting the backup, and proceed without one. The
	# failsafe arm at the end of this function records this fact via
	# the absence of a rootfs_backup.bin in priv_data, so
	# mercury_restore_rootfs() will safely no-op if it is called.
	# ------------------------------------------------------------
	local first_install=0
	if [ -z "$(mercury_find_ubi_rootfs_dev)" ]; then
		echo "Mercury: No rootfs UBI volume found - first install (skipping backup)."
		first_install=1
	elif ! mercury_backup_rootfs; then
		echo "Mercury: ERROR - could not back up the current rootfs, aborting upgrade."
		echo "Mercury: Nothing has been written yet - the device is unchanged."
		return 1
	fi

	local fw_image="/tmp/firmware.bin"
	local root_image="/tmp/rootfs.bin"
	local kernel_path root_path
	if ! tar -tf "$image_file" >/dev/null 2>&1; then
		echo "Mercury: ERROR - image is not a sysupgrade tar (got a bare kernel-only"
		echo "         image?). This device needs the kernel AND rootfs together -"
		echo "         see the comment above mercury_find_ubi_rootfs_dev() for why."
		return 1
	fi

	echo "Mercury: Detected sysupgrade tar format, extracting kernel + root..."
	kernel_path="$(tar -tf "$image_file" | grep '/kernel$' | sed -n '1p')"
	root_path="$(tar -tf "$image_file" | grep '/root$' | sed -n '1p')"
	if [ -z "$kernel_path" ]; then
		echo "Mercury: ERROR - No kernel found in sysupgrade tar"
		return 1
	fi
	if [ -z "$root_path" ]; then
		echo "Mercury: ERROR - No root (rootfs) found in sysupgrade tar."
		echo "         Refusing to flash a kernel with no matching rootfs -"
		echo "         that combination does not boot on this device."
		return 1
	fi

	tar -xOf "$image_file" "$kernel_path" > "$fw_image" 2>/dev/null
	if [ ! -s "$fw_image" ]; then
		echo "Mercury: ERROR - Failed to extract kernel from sysupgrade tar"
		rm -f "$fw_image"
		return 1
	fi
	echo "Mercury: Extracted kernel from: $kernel_path"

	tar -xOf "$image_file" "$root_path" > "$root_image" 2>/dev/null
	if [ ! -s "$root_image" ]; then
		echo "Mercury: ERROR - Failed to extract root from sysupgrade tar"
		rm -f "$fw_image" "$root_image"
		return 1
	fi
	echo "Mercury: Extracted root from: $root_path"

	local fw_size root_size
	fw_size=$(stat -c%s "$fw_image" 2>/dev/null || wc -c < "$fw_image")
	root_size=$(stat -c%s "$root_image" 2>/dev/null || wc -c < "$root_image")
	echo "Mercury: kernel image size: $fw_size bytes, root image size: $root_size bytes"
	if [ "$fw_size" -lt 1000000 ]; then
		echo "Mercury: ERROR - kernel image too small (corrupt?)"
		rm -f "$fw_image" "$root_image"
		return 1
	fi
	if [ "$root_size" -lt 1000000 ]; then
		echo "Mercury: ERROR - root image too small (corrupt?)"
		rm -f "$fw_image" "$root_image"
		return 1
	fi

	local rootfs_ubi_dev rootfs_ubi_size
	rootfs_ubi_dev=$(mercury_find_ubi_rootfs_dev)
	if [ -z "$rootfs_ubi_dev" ]; then
		if [ "$first_install" = "1" ]; then
			# First install: the "ubi" sub-partition has never been
			# formatted. Format it, attach it, create the "rootfs"
			# static volume at maximum size, then re-probe.
			local ubi_mtd_num
			ubi_mtd_num=$(mercury_get_mtd_num "ubi")
			if [ -z "$ubi_mtd_num" ]; then
				echo "Mercury: ERROR - Cannot find 'ubi' partition for rootfs initialization"
				rm -f "$fw_image" "$root_image"
				return 1
			fi
			ubidetach -m "$ubi_mtd_num" 2>/dev/null
			echo "Mercury: First install - formatting UBI on mtd${ubi_mtd_num}..."
			if ! ubiformat -y "/dev/mtd${ubi_mtd_num}"; then
				echo "Mercury: ERROR - ubiformat failed on mtd${ubi_mtd_num}"
				rm -f "$fw_image" "$root_image"
				return 1
			fi
			echo "Mercury: Attaching UBI on mtd${ubi_mtd_num}..."
			if ! ubiattach -m "$ubi_mtd_num"; then
				echo "Mercury: ERROR - ubiattach failed after format"
				rm -f "$fw_image" "$root_image"
				return 1
			fi
			local new_ubi_num="" ubi_sysfs
			for ubi_sysfs in /sys/class/ubi/ubi[0-9]*; do
				[ -d "$ubi_sysfs" ] || continue
				local m
				m="$(cat "$ubi_sysfs/mtd_num" 2>/dev/null)"
				if [ "$m" = "$ubi_mtd_num" ]; then
					new_ubi_num="$(basename "$ubi_sysfs")"
					new_ubi_num="${new_ubi_num#ubi}"
					break
				fi
			done
			if [ -z "$new_ubi_num" ]; then
				echo "Mercury: ERROR - Cannot find newly attached UBI device"
				rm -f "$fw_image" "$root_image"
				return 1
			fi
			# Size the rootfs volume to exactly the squashfs size so
			# that the remaining UBI space can be claimed later by the
			# rootfs_data overlay volume (created on first boot by
			# OpenWrt's init). Using -m would leave no room for it.
			echo "Mercury: Creating rootfs volume on ubi${new_ubi_num} (size=${root_size})..."
			if ! ubimkvol "/dev/ubi${new_ubi_num}" -N rootfs -s "$root_size"; then
				echo "Mercury: ERROR - ubimkvol failed on ubi${new_ubi_num}"
				rm -f "$fw_image" "$root_image"
				return 1
			fi
			rootfs_ubi_dev=$(mercury_find_ubi_rootfs_dev)
		fi
		if [ -z "$rootfs_ubi_dev" ]; then
			echo "Mercury: ERROR - could not find the 'rootfs' UBI volume to write to"
			rm -f "$fw_image" "$root_image"
			return 1
		fi
	fi
	rootfs_ubi_size=$(mercury_ubi_vol_size "$rootfs_ubi_dev")
	if [ -n "$rootfs_ubi_size" ] && [ "$root_size" -gt "$rootfs_ubi_size" ]; then
		echo "Mercury: ERROR - new root ($root_size bytes) is bigger than the"
		echo "         rootfs UBI volume ($rootfs_ubi_size bytes). Refusing to write"
		echo "         a rootfs that cannot possibly fit."
		rm -f "$fw_image" "$root_image"
		return 1
	fi

	echo "Mercury: Writing kernel to $target_part (erasing first via mtd)..."
	if ! mtd write "$fw_image" "$target_part"; then
		echo "Mercury: ERROR - Failed to write kernel"
		echo "Mercury: Boot slot NOT switched - device will still boot the old,"
		echo "         untouched slot $current_slot on next boot."
		rm -f "$fw_image" "$root_image"
		return 1
	fi
	echo "Mercury: Kernel write completed"
	rm -f "$fw_image"

	# The rootfs volume is shared across both banks (see comment above
	# mercury_find_ubi_rootfs_dev), so this write affects the system
	# regardless of which bank ends up selected. That is exactly why
	# the backup above exists: if this pair does not come up healthy,
	# 95mercuryfailsafe restores this same backup alongside reverting
	# the boot slot, so old-kernel-with-new-rootfs can never happen.
	echo "Mercury: Writing new rootfs to $rootfs_ubi_dev via ubiupdatevol..."
	if ! ubiupdatevol "$rootfs_ubi_dev" "$root_image"; then
		echo "Mercury: ERROR - Failed to write rootfs"
		echo "Mercury: Boot slot NOT switched. Restoring original rootfs from backup..."
		mercury_restore_rootfs
		rm -f "$root_image"
		return 1
	fi
	echo "Mercury: Rootfs write completed"
	rm -f "$root_image"

	if ! mercury_switch_boot_slot "$config_mtd" "$target_slot"; then
		echo "Mercury: ERROR - Failed to switch boot slot"
		echo "Mercury: WARNING - Kernel+rootfs written but boot slot not switched!"
		echo "Mercury: Restoring original rootfs from backup to avoid a mismatch..."
		mercury_restore_rootfs
		return 1
	fi

	echo "Mercury: Arming boot failsafe (revert kernel slot to $current_slot AND"
	echo "         restore the pre-upgrade rootfs if slot $target_slot does not"
	echo "         come up healthy)..."
	if mercury_mount_data; then
		echo "prev_slot=$current_slot" > "$MERCURY_DATA_MOUNT/pending_boot"
		echo "new_slot=$target_slot" >> "$MERCURY_DATA_MOUNT/pending_boot"
		sync
		mercury_umount_data
	else
		echo "Mercury: WARNING - Could not arm boot failsafe (priv_data unavailable), continuing without it"
	fi

	echo "Mercury: Upgrade complete! Rebooting to slot $target_slot..."
	sync
	reboot -f
}
