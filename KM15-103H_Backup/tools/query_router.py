import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.77.1', 22, 'root', 'Admin-12345', timeout=10)

cmds = [
    'ls -la /sys/bus/nvmem/devices/',
    'for dev in /sys/bus/nvmem/devices/*; do echo "=== $dev ==="; ls -l "$dev"; done',
    'iw dev',
    'iw reg get',
    'cat /proc/cmdline'
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
