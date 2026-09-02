import os
import sys
import paramiko
import scp

ROUTER_IP = "192.168.77.1"
ROUTER_PORT = 22
ROUTER_USER = "root"
ROUTER_PASS = "Admin-12345"

OUTPUT_DIR = r"c:\Users\hp\OneDrive\Desktop\New folder (3)\hub\Horus-OpenWrt-Final\KM15-103H_Backup"

def run_extraction():
    print(f"Connecting to {ROUTER_IP}...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(ROUTER_IP, ROUTER_PORT, ROUTER_USER, ROUTER_PASS, timeout=15)
    print("Connected successfully!\n")

    # List of commands to gather system details
    commands = {
        "openwrt_release.txt": "cat /etc/openwrt_release",
        "uname.txt": "uname -a; cat /proc/version",
        "cpuinfo.txt": "cat /proc/cpuinfo",
        "meminfo.txt": "cat /proc/meminfo",
        "mtd.txt": "cat /proc/mtd",
        "partitions.txt": "cat /proc/partitions",
        "board_json.txt": "cat /etc/board.json",
        "ubus_board.txt": "ubus call system board",
        "dt_model.txt": "cat /proc/device-tree/model; echo ''; tr '\\0' '\\n' < /proc/device-tree/compatible",
        "dmesg.txt": "dmesg",
        "dmesg_wifi_eeprom.txt": "dmesg | grep -i -E 'eeprom|factory|caldata|art|mt76|mt79|ath|ralink|wifi|wlan|error|warn|failed|mac|invalid'",
        "lsmod.txt": "lsmod",
        "lspci.txt": "lspci -nn -vv 2>&1",
        "lsusb.txt": "lsusb 2>&1",
        "iwinfo.txt": "iwinfo 2>&1; echo '=== iw dev ==='; iw dev 2>&1; echo '=== iw phy ==='; iw phy 2>&1",
        "wireless_config.txt": "cat /etc/config/wireless",
        "network_config.txt": "cat /etc/config/network",
        "system_config.txt": "cat /etc/config/system",
        "firewall_config.txt": "cat /etc/config/firewall",
        "dhcp_config.txt": "cat /etc/config/dhcp",
        "swconfig.txt": "swconfig dev switch0 show 2>&1; ip link 2>&1; bridge link 2>&1",
        "firmware_dir.txt": "ls -laR /lib/firmware/ 2>&1",
        "hotplug_firmware.txt": "ls -la /etc/hotplug.d/firmware/ 2>&1; cat /etc/hotplug.d/firmware/* 2>&1",
        "mount_df.txt": "df -h; echo ''; mount",
        "ubus_list.txt": "ubus list"
    }

    print("--- Executing System Diagnostic Commands ---")
    for fname, cmd in commands.items():
        print(f"Running: {cmd} -> {fname}")
        stdin, stdout, stderr = ssh.exec_command(cmd)
        out = stdout.read().decode('utf-8', errors='replace')
        err = stderr.read().decode('utf-8', errors='replace')
        filepath = os.path.join(OUTPUT_DIR, fname)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(out)
            if err:
                f.write("\n=== STDERR ===\n" + err)

    # Now dump MTD partitions (Bootloader, Config, Factory) and FDT (Device Tree)
    print("\n--- Dumping Critical Partitions and Device Tree Blob ---")
    dump_cmds = [
        "dd if=/dev/mtd0 of=/tmp/mtd0_Bootloader.bin bs=64k",
        "dd if=/dev/mtd1 of=/tmp/mtd1_Config.bin bs=64k",
        "dd if=/dev/mtd2 of=/tmp/mtd2_Factory.bin bs=64k",
        "cp /sys/firmware/fdt /tmp/device_tree.dtb 2>/dev/null || true",
        "md5sum /tmp/mtd0_Bootloader.bin /tmp/mtd1_Config.bin /tmp/mtd2_Factory.bin /tmp/device_tree.dtb"
    ]
    for cmd in dump_cmds:
        print(f"Running on router: {cmd}")
        stdin, stdout, stderr = ssh.exec_command(cmd)
        out = stdout.read().decode('utf-8', errors='replace')
        print(out.strip())

    # Download files via SSH streaming with MD5 verification
    print("\n--- Downloading dumps via SSH streaming ---")
    remote_files = [
        "/tmp/mtd0_Bootloader.bin",
        "/tmp/mtd1_Config.bin",
        "/tmp/mtd2_Factory.bin",
        "/tmp/device_tree.dtb"
    ]
    import hashlib
    for rfile in remote_files:
        local_name = os.path.basename(rfile)
        local_path = os.path.join(OUTPUT_DIR, local_name)
        print(f"Downloading {rfile} -> {local_path} ...")
        stdin, stdout, stderr = ssh.exec_command(f"cat {rfile}")
        data = stdout.read()
        with open(local_path, "wb") as f:
            f.write(data)
        calc_md5 = hashlib.md5(data).hexdigest()
        print(f"  Saved {len(data)} bytes, MD5: {calc_md5}")

    # Remove temporary dumps on router
    ssh.exec_command("rm -f /tmp/mtd0_Bootloader.bin /tmp/mtd1_Config.bin /tmp/mtd2_Factory.bin /tmp/device_tree.dtb")
    
    ssh.close()
    print("\nDone! All diagnostic information and partition dumps saved to:")
    print(OUTPUT_DIR)

if __name__ == "__main__":
    run_extraction()
