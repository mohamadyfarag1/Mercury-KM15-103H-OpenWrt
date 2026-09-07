#!/bin/sh
# Mercury KM15-103H sysupgrade platform hook for Breed bootloader.

. /lib/upgrade/nand.sh

platform_check_image() {
	return 0
}

platform_do_upgrade() {
	CI_KERNPART="firmware"
	CI_UBIPART="ubi"
	nand_do_upgrade "$1"
}
