import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.77.1', 22, 'root', 'Admin-12345', timeout=10)

cmds = [
    'iw phy phy1 info | grep -i -E "160|width|vht|he cap"',
    'iw phy phy1 info | grep -A 20 "VHT Capabilities"',
    'iw phy phy1 info | grep -A 35 "HE Capabilities"',
    'iw phy phy1 info | grep -A 35 "HE PHY Capabilities"',
    'cat /sys/bus/pci/devices/0000:02:00.0/device',
    'cat /sys/bus/pci/devices/0000:02:00.0/subsystem_device',
    'cat /sys/bus/pci/devices/0000:02:00.0/subsystem_vendor'
]

for cmd in cmds:
    print(f"\n=================== {cmd} ===================")
    stdin, stdout, stderr = ssh.exec_command(cmd)
    out = stdout.read().decode('utf-8', errors='replace').strip()
    if out:
        print(out)
    err = stderr.read().decode('utf-8', errors='replace').strip()
    if err:
        print("[ERR]:", err)

ssh.close()
