import os
import subprocess
import paramiko
from db import execute

FLAMEGRAPH_BIN    = os.environ.get('FLAMEGRAPH_BIN',    '/opt/flamegraph/flamegraph.pl')
STACKCOLLAPSE_BIN = os.environ.get('STACKCOLLAPSE_BIN', '/opt/flamegraph/stackcollapse-perf.pl')
FLAMEGRAPH_DIR    = os.environ.get('FLAMEGRAPH_DIR',    '/data/flamegraphs')


def _ssh_connect(device):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=device['ip_addr'],
        username=os.environ.get('SSH_USER', 'root'),
        port=int(os.environ.get('SSH_PORT', 22)),
        timeout=30,
    )
    return client


def start_flamegraph_job(fg_id, device, revision_str, flask_app, duration_s=15):
    """Runs in a background thread. Pushes Flask app context for DB access."""
    with flask_app.app_context():
        execute('UPDATE bw_flamegraphs SET status=%s WHERE id=%s', ('running', fg_id))
        try:
            ssh = _ssh_connect(device)
            remote_perf = f'/tmp/bw-perf-{fg_id}.data'

            stdin, stdout, stderr = ssh.exec_command(
                f'perf record -ag -o {remote_perf} sleep {duration_s}',
                timeout=duration_s + 30
            )
            stdout.channel.recv_exit_status()

            os.makedirs(FLAMEGRAPH_DIR, exist_ok=True)
            local_perf = os.path.join(FLAMEGRAPH_DIR, f'perf-{fg_id}.data')
            sftp = ssh.open_sftp()
            sftp.get(remote_perf, local_perf)
            sftp.close()
            ssh.exec_command(f'rm -f {remote_perf}')
            ssh.close()

            svg_path = os.path.join(FLAMEGRAPH_DIR, f'flamegraph-{fg_id}.svg')
            with open(svg_path, 'wb') as svg_out:
                p1 = subprocess.Popen(
                    ['perf', 'script', '-i', local_perf],
                    stdout=subprocess.PIPE
                )
                p2 = subprocess.Popen(
                    ['perl', STACKCOLLAPSE_BIN],
                    stdin=p1.stdout, stdout=subprocess.PIPE
                )
                p1.stdout.close()
                p3 = subprocess.Popen(
                    ['perl', FLAMEGRAPH_BIN],
                    stdin=p2.stdout, stdout=svg_out
                )
                p2.stdout.close()
                p3.wait()

            execute(
                'UPDATE bw_flamegraphs SET status=%s, svg_path=%s, perf_data_path=%s WHERE id=%s',
                ('done', svg_path, local_perf, fg_id)
            )
        except Exception:
            execute('UPDATE bw_flamegraphs SET status=%s WHERE id=%s', ('failed', fg_id))
            raise
