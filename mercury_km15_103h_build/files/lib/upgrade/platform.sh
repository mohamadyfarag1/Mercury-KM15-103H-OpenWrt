#!/bin/sh
# Mercury KM15-103H sysupgrade platform hook.
# Replaces the generic ramips platform.sh so that mercury_do_upgrade()
# is what runs, not the generic nand_do_upgrade().

. /lib/upgrade/nand.sh
. /lib/upgrade/mercury.sh

platform_check_image() { return 0; }

platform_do_upgrade() {
	mercury_do_upgrade "$1"
}
