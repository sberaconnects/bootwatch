#!/usr/bin/env python3
"""SSH into one device, collect boot + perf data, POST to BootWatch server."""
import argparse
import json
import re
import sys
import urllib.request
import urllib.error
import paramiko


def ssh_run(client, cmd, timeout=60):
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    rc  = stdout.channel.recv_exit_status()
    return out, err, rc


def parse_analyze(output):
    """Extract total boot time from `systemd-analyze` output.
    Line: 'Startup finished in 1.2s (kernel) + 43.9s (userspace) = 45.2s'
    Returns float seconds or None."""
    m = re.search(r'=\s*([\d.]+)s', output)
    return float(m.group(1)) if m else None


def parse_blame(output):
    """Parse `systemd-analyze blame` output.
    Lines: '  18.450s NetworkManager.service'
    Returns list of {service, time_s}."""
    entries = []
    for line in output.strip().splitlines():
        m = re.match(r'\s*([\d.]+)s\s+(.+)', line)
        if m:
            entries.append({'service': m.group(2).strip(), 'time_s': float(m.group(1))})
    return entries


def parse_perf_stat(output, duration_s):
    """Parse `perf stat` stderr/stdout for key counters."""
    def extract(pattern):
        m = re.search(pattern, output, re.MULTILINE)
        return m.group(1).replace(',', '') if m else None

    cycles_s       = extract(r'([\d,]+)\s+cycles')
    instructions_s = extract(r'([\d,]+)\s+instructions')
    ipc_s          = extract(r'#\s+([\d.]+)\s+insn per cycle')
    cmiss_s        = extract(r'([\d,]+)\s+cache-misses')
    cref_s         = extract(r'([\d,]+)\s+cache-references')
    bmiss_s        = extract(r'([\d,]+)\s+branch-misses')
    btot_s         = extract(r'([\d,]+)\s+branches')

    cycles        = int(cycles_s)        if cycles_s        else None
    instructions  = int(instructions_s)  if instructions_s  else None
    ipc           = float(ipc_s)         if ipc_s           else None
    cache_misses  = int(cmiss_s)         if cmiss_s         else None
    cache_refs    = int(cref_s)          if cref_s          else None
    branch_misses = int(bmiss_s)         if bmiss_s         else None
    branch_total  = int(btot_s)          if btot_s          else None

    cache_miss_pct  = (cache_misses / cache_refs * 100)    if cache_misses and cache_refs    else None
    branch_miss_pct = (branch_misses / branch_total * 100) if branch_misses and branch_total else None

    return {
        'duration_s':      duration_s,
        'cycles':          cycles,
        'instructions':    instructions,
        'ipc':             ipc,
        'cache_misses':    cache_misses,
        'cache_refs':      cache_refs,
        'cache_miss_pct':  cache_miss_pct,
        'branch_misses':   branch_misses,
        'branch_total':    branch_total,
        'branch_miss_pct': branch_miss_pct,
        'raw_output':      output,
    }


def detect_revision(client):
    out, _, _ = ssh_run(client, 'grep ^VERSION_ID= /etc/os-release || echo VERSION_ID=unknown')
    m = re.search(r'VERSION_ID="?([^"\n]+)"?', out)
    return m.group(1) if m else 'unknown'


def main():
    parser = argparse.ArgumentParser(description='BootWatch single-device collector')
    parser.add_argument('--device',        required=True,          help='Device IP address')
    parser.add_argument('--server',        default='127.0.0.1',    help='BootWatch server IP')
    parser.add_argument('--port',          default=8080, type=int, help='BootWatch server port')
    parser.add_argument('--ssh-user',      default='root',         help='SSH username')
    parser.add_argument('--ssh-port',      default=22,   type=int, help='SSH port')
    parser.add_argument('--ssh-key',       default=None,           help='Path to SSH private key')
    parser.add_argument('--name',          default='device',       help='Device name')
    parser.add_argument('--label',         default='',             help='Device label')
    parser.add_argument('--version',       default=None,           help='SW revision (auto-detect if omitted)')
    parser.add_argument('--skip-perf',     action='store_true',    help='Skip perf stat collection')
    parser.add_argument('--perf-duration', default=10,   type=int, help='perf stat window in seconds')
    args = parser.parse_args()

    print(f'[*] Connecting to {args.device}:{args.ssh_port} as {args.ssh_user}')
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    kw = dict(hostname=args.device, username=args.ssh_user, port=args.ssh_port, timeout=30)
    if args.ssh_key:
        kw['key_filename'] = args.ssh_key
    client.connect(**kw)

    revision = args.version or detect_revision(client)
    print(f'[*] Revision: {revision}')

    print('[*] Running systemd-analyze...')
    out, _, _ = ssh_run(client, 'systemd-analyze')
    boot_time = parse_analyze(out)
    if boot_time is None:
        print('[!] Could not parse boot time', file=sys.stderr)
        print(out, file=sys.stderr)
        sys.exit(1)
    print(f'[*] Boot time: {boot_time:.1f}s')

    print('[*] Running systemd-analyze blame...')
    blame_out, _, _ = ssh_run(client, 'systemd-analyze blame')
    blame = parse_blame(blame_out)
    print(f'[*] {len(blame)} blame entries')

    print('[*] Running systemd-analyze critical-chain...')
    chain_out, _, _ = ssh_run(client, 'systemd-analyze critical-chain')

    perf_stat = None
    if not args.skip_perf:
        print(f'[*] Running perf stat (duration={args.perf_duration}s)...')
        perf_out, perf_err, _ = ssh_run(
            client,
            f'perf stat -a sleep {args.perf_duration} 2>&1',
            timeout=args.perf_duration + 30
        )
        combined = perf_out + perf_err
        if combined.strip():
            perf_stat = parse_perf_stat(combined, args.perf_duration)
            print(f'[*] perf IPC: {perf_stat["ipc"]}')
        else:
            print('[!] perf stat returned no output — skipping', file=sys.stderr)

    client.close()

    payload = {
        'device_ip':    args.device,
        'device_name':  args.name,
        'device_label': args.label,
        'revision':     revision,
        'source':       'ssh_pull',
        'boot_time_s':  boot_time,
        'blame':        blame,
        'critical_chain': chain_out,
        'raw_blame':    blame_out,
    }
    if perf_stat:
        payload['perf_stat'] = perf_stat

    url = f'http://{args.server}:{args.port}/api/boot'
    print(f'[*] POST {url}')
    body = json.dumps(payload).encode('utf-8')
    req  = urllib.request.Request(url, data=body, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            print(f'[+] Recorded boot_id={result["boot_id"]}')
    except urllib.error.HTTPError as e:
        print(f'[!] HTTP {e.code}: {e.read().decode()}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
