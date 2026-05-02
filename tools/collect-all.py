#!/usr/bin/env python3
"""Run collect.py in parallel across multiple devices."""
import argparse
import subprocess
import sys
import concurrent.futures
from pathlib import Path

COLLECT = Path(__file__).parent / 'collect.py'


def collect_one(device_line, common_args):
    parts = device_line.strip().split()
    if not parts or parts[0].startswith('#'):
        return None
    ip    = parts[0]
    name  = parts[1] if len(parts) > 1 else ip.replace('.', '-')
    label = parts[2] if len(parts) > 2 else ''
    cmd = [sys.executable, str(COLLECT), '--device', ip, '--name', name, '--label', label] + common_args
    result = subprocess.run(cmd, capture_output=True, text=True)
    prefix = f'[{name}]'
    for line in (result.stdout + result.stderr).splitlines():
        print(f'{prefix} {line}', flush=True)
    return name, result.returncode


def main():
    parser = argparse.ArgumentParser(description='BootWatch multi-device collector')
    parser.add_argument('--devices-file', default='tools/devices.txt', help='Path to devices list file')
    parser.add_argument('--devices',      nargs='+', help='Device IPs directly (overrides --devices-file)')
    parser.add_argument('--server',       default='127.0.0.1')
    parser.add_argument('--port',         default=8080, type=int)
    parser.add_argument('--ssh-user',     default='root')
    parser.add_argument('--ssh-port',     default=22,   type=int)
    parser.add_argument('--ssh-key',      default=None)
    parser.add_argument('--version',      default=None)
    parser.add_argument('--skip-perf',    action='store_true')
    parser.add_argument('--perf-duration',default=10, type=int)
    parser.add_argument('--threads',      default=4, type=int)
    args = parser.parse_args()

    common = ['--server', args.server, '--port', str(args.port),
              '--ssh-user', args.ssh_user, '--ssh-port', str(args.ssh_port)]
    if args.ssh_key:      common += ['--ssh-key', args.ssh_key]
    if args.version:      common += ['--version', args.version]
    if args.skip_perf:    common.append('--skip-perf')
    common += ['--perf-duration', str(args.perf_duration)]

    if args.devices:
        lines = args.devices
    else:
        with open(args.devices_file) as f:
            lines = [l for l in f if l.strip() and not l.strip().startswith('#')]

    print(f'[*] Collecting from {len(lines)} device(s) with {args.threads} threads')
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.threads) as ex:
        futures = [ex.submit(collect_one, line, common) for line in lines]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    failed = [r for r in results if r and r[1] != 0]
    if failed:
        print(f'[!] {len(failed)} device(s) failed: {[r[0] for r in failed]}', file=sys.stderr)
        sys.exit(1)
    print(f'[+] All {len(lines)} device(s) collected successfully')


if __name__ == '__main__':
    main()
