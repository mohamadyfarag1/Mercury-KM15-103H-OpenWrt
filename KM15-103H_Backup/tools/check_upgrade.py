import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.77.1', 22, 'root', 'Admin-12345', timeout=10)

cmds = [
    'grep -rn "mercury_do_upgrade" /lib/ /etc/ 2>/dev/null',
    'ls -la /lib/upgrade/',
    'cat /lib/upgrade/platform.sh | head -n 45',
    'fw_printenv 2>/dev/null'
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
