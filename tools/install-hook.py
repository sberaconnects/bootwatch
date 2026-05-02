#!/usr/bin/env python3
"""Install boot-time reporting service on a device via SSH."""
import argparse
import sys
import paramiko

REPORT_SCRIPT = r"""#!/bin/sh
# BootWatch boot-time reporter — installed by install-hook.py
SERVER="{server}"
PORT="{port}"
VERSION_KEY="{version_key}"

BOOT_TIME=$(systemd-analyze 2>/dev/null | grep -oP '= \K[\d.]+(?=s)')
REVISION=$(grep "^${{VERSION_KEY}}=" /etc/os-release 2>/dev/null | cut -d= -f2 | tr -d '"')
REVISION=${{REVISION:-unknown}}
DEVICE_IP=$(hostname -I | awk '{{print $1}}')
DEVICE_NAME=$(hostname)

BLAME_OUT=$(systemd-analyze blame 2>/dev/null || true)
CHAIN_OUT=$(systemd-analyze critical-chain 2>/dev/null || true)

# Build blame JSON array
BLAME_JSON=$(echo "$BLAME_OUT" | awk '
  /^[[:space:]]*[0-9]+\.[0-9]+s/ {{
    gsub(/^[[:space:]]+|[[:space:]]+$/, "");
    split($0, a, /[[:space:]]+/);
    # a[1]=time a[2]=service
    t=a[1]; sub(/s$/, "", t);
    svc=a[2];
    printf "{{\"service\":\"%s\",\"time_s\":%s}},", svc, t
  }}
' | sed 's/,$//')

curl -sf -X POST -H "Content-Type: application/json" \
  -d "{{
    \"device_ip\": \"$DEVICE_IP\",
    \"device_name\": \"$DEVICE_NAME\",
    \"device_label\": \"\",
    \"revision\": \"$REVISION\",
    \"source\": \"boot_hook\",
    \"boot_time_s\": ${{BOOT_TIME:-0}},
    \"blame\": [$BLAME_JSON],
    \"critical_chain\": \"$(echo "$CHAIN_OUT" | head -20 | tr '"' "'" | tr '\n' ' ')\"
  }}" "http://$SERVER:$PORT/api/boot" || true
"""

SYSTEMD_UNIT = """\
[Unit]
Description=BootWatch boot time reporter
After=multi-user.target
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/bootwatch-report.sh
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
"""


def ssh_run(client, cmd):
    _, stdout, _ = client.exec_command(cmd)
    stdout.channel.recv_exit_status()
    return stdout.read().decode()


def main():
    parser = argparse.ArgumentParser(description='Install BootWatch boot hook on device')
    parser.add_argument('--device',      required=True)
    parser.add_argument('--server',      default='127.0.0.1')
    parser.add_argument('--port',        default=8080, type=int)
    parser.add_argument('--ssh-user',    default='root')
    parser.add_argument('--ssh-port',    default=22,   type=int)
    parser.add_argument('--ssh-key',     default=None)
    parser.add_argument('--version-key', default='VERSION_ID', help='Key in /etc/os-release for SW revision')
    args = parser.parse_args()

    print(f'[*] Connecting to {args.device}')
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    kw = dict(hostname=args.device, username=args.ssh_user, port=args.ssh_port, timeout=30)
    if args.ssh_key:
        kw['key_filename'] = args.ssh_key
    client.connect(**kw)

    script = REPORT_SCRIPT.format(server=args.server, port=args.port, version_key=args.version_key)

    sftp = client.open_sftp()
    with sftp.open('/usr/local/bin/bootwatch-report.sh', 'w') as f:
        f.write(script)
    ssh_run(client, 'chmod +x /usr/local/bin/bootwatch-report.sh')
    print('[*] Installed /usr/local/bin/bootwatch-report.sh')

    with sftp.open('/etc/systemd/system/bootwatch-report.service', 'w') as f:
        f.write(SYSTEMD_UNIT)
    sftp.close()
    print('[*] Installed /etc/systemd/system/bootwatch-report.service')

    ssh_run(client, 'systemctl daemon-reload')
    ssh_run(client, 'systemctl enable bootwatch-report.service')
    ssh_run(client, 'systemctl start bootwatch-report.service')
    print('[+] Service enabled and started — will run on every boot')
    client.close()


if __name__ == '__main__':
    main()
