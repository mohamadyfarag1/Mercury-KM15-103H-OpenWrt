import paramiko
import sys

print("Testing connection to 192.168.77.1...")
try:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect('192.168.77.1', 22, 'root', 'Admin-12345', timeout=10)
    print("SSH Authentication successful!")
    
    stdin, stdout, stderr = ssh.exec_command('uname -a; cat /etc/openwrt_release; cat /proc/mtd')
    print("=== COMMAND OUTPUT ===")
    print(stdout.read().decode('utf-8', errors='replace'))
    print("=== STDERR ===")
    print(stderr.read().decode('utf-8', errors='replace'))
    ssh.close()
except Exception as e:
    print(f"Error: {type(e).__name__}: {e}")
