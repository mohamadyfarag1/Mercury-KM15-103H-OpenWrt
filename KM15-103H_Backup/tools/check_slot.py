import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.77.1', 22, 'root', 'Admin-12345', timeout=10)

cmds = [
    'dd if=/dev/mtd1 bs=1 skip=10 count=1 2>/dev/null | hexdump -e \'"Boot Slot: %d\\n"\'',
    'cat /proc/mounts | grep -E "ubi|root"',
    'df -h'
]
for cmd in cmds:
    print(f"=== {cmd} ===")
    stdin, stdout, stderr = ssh.exec_command(cmd)
    print(stdout.read().decode().strip())

ssh.close()
