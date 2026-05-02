# BootWatch

Self-hosted boot analysis UI for embedded Linux devices. Tracks `systemd-analyze` blame, critical chain, and `perf` counters per boot — visualized across devices and firmware revisions.

## Quick Start (local)

```bash
cp .env.example .env
# Edit .env — set DB_ROOT_PASSWORD, DB_PASSWORD, SECRET_KEY
docker compose -f docker-compose.yml -f docker-compose-local.yml up -d
# UI at http://localhost:8080
```

## Collect from a device

```bash
pip install paramiko
python3 tools/collect.py --device 192.168.1.100 --name my-device --server 127.0.0.1 --port 8080
```

## Collect from multiple devices

```bash
cp tools/devices.txt.example tools/devices.txt
# Edit devices.txt — one device per line: IP name label
python3 tools/collect-all.py --devices-file tools/devices.txt --server 127.0.0.1
```

## Install boot hook (auto-report on every boot)

```bash
python3 tools/install-hook.py --device 192.168.1.100 --server 10.0.0.5 --port 8080
```

## Pages

| Page | URL | Description |
|------|-----|-------------|
| Overview | `/` | Device grid with sparklines, recent boots, slowest services |
| Boots | `/boots` | Paginated boot list, filterable by device/revision/date/service |
| Boot detail | `/boot/<id>` | Blame table, boot time trend chart, critical chain |
| Devices | `/devices` | All devices with avg/min/max boot stats |
| Device detail | `/device/<id>` | Per-device boot history |
| Firmware | `/firmware` | Per-revision boot time comparison |
| Services | `/services` | Fleet-wide service timing, click-through to affected boots |
| Perf | `/perf` | CPU counters (IPC, cache miss, branch miss) + on-demand flamegraph |

## Data collection options

| Method | When | How |
|--------|------|-----|
| SSH pull | On demand | Run `collect.py` or `collect-all.py` manually or via cron |
| Boot hook | Automatic on every boot | Install with `install-hook.py` |

## Production deployment (Traefik + TLS)

```bash
# Edit .env: set DOMAIN=bootwatch.yourdomain.com, ACME_EMAIL=you@example.com
docker compose -f docker-compose.yml -f docker-compose-production.yml up -d
```

## Running tests

```bash
# Requires running MariaDB (docker compose up -d mariadb)
cd web && python3 -m pytest ../tests/ -v
```
