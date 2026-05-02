# BootWatch — Design Spec

**Date:** 2026-05-02
**Project:** Standalone (new repo, not part of CrashWeb)
**Deployment:** Single developer on local PC via Docker Compose; or centrally hosted for a team.

---

## Overview

BootWatch is a self-hosted web UI for collecting, visualizing, and analyzing boot performance data from embedded Linux devices. It tracks `systemd-analyze` blame + critical chain per boot event, `perf stat` CPU counters, and on-demand flamegraphs — all pulled from devices over SSH. Designed to spot boot time regressions across firmware revisions and identify slow systemd services fleet-wide.

---

## Tech Stack

| Component | Choice | Notes |
|-----------|--------|-------|
| Web framework | Flask (Python 3) | Same as CrashWeb |
| Database | MariaDB 10.6 | Same as CrashWeb |
| Reverse proxy | Traefik 3.x | Same as CrashWeb (optional for local use) |
| Containerization | Docker Compose | Same as CrashWeb |
| UI theme | Tokyo Night (inline CSS) | Same palette as CrashWeb: canvas `#1a1b26`, surface `#24283b`, accent `#7aa2f7` |
| Flamegraph generation | FlameGraph (Brendan Gregg's `flamegraph.pl`) | Perl script, bundled in container |
| SSH client | paramiko (Python) | Same as CrashWeb collect.py |
| Charts | Pure CSS bars + sparklines | No JS charting library — keeps it simple |

---

## Deployment Modes

### Local (developer PC, no TLS)
```bash
docker compose -f docker-compose.yml -f docker-compose-local.yml up -d
# UI at http://localhost:8080
```

### Central (team server, TLS via Traefik)
```bash
docker compose -f docker-compose.yml -f docker-compose-production.yml up -d
# UI at https://bootwatch.yourdomain.com
```

---

## Pages

| Page | URL | Description |
|------|-----|-------------|
| Overview | `/` | Stat cards, device grid with sparklines, recent boots, slowest services fleet-wide |
| Boots | `/boots` | Paginated list of all boot events, filterable by device/revision/date |
| Boot detail | `/boot/<id>` | Blame table + boot time trend + critical chain for one boot event |
| Devices | `/devices` | All devices: name, IP, latest boot time, avg boot time, boot count |
| Device detail | `/device/<id>` | Per-device boot history and stats |
| Firmware | `/firmware` | Per-SW-revision avg boot time — spot regressions between versions |
| Services | `/services` | Fleet-wide service view: avg time, worst device, trend across revisions |
| Perf | `/perf` | perf stat counters per device/revision + on-demand flamegraph generation |

---

## Database Schema

### `bw_devices`
```sql
CREATE TABLE bw_devices (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(128) NOT NULL,
    label       VARCHAR(128) DEFAULT '',
    ip_addr     VARCHAR(64)  NOT NULL,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY (ip_addr)
);
```

### `bw_sw_revisions`
```sql
CREATE TABLE bw_sw_revisions (
    id       INT AUTO_INCREMENT PRIMARY KEY,
    revision VARCHAR(128) NOT NULL UNIQUE
);
```

### `bw_boots`
```sql
CREATE TABLE bw_boots (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    device_id    INT NOT NULL REFERENCES bw_devices(id),
    revision_id  INT NOT NULL REFERENCES bw_sw_revisions(id),
    boot_time_s  FLOAT NOT NULL,          -- total boot time in seconds
    collected_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    source       ENUM('ssh_pull','boot_hook') DEFAULT 'ssh_pull',
    raw_blame    TEXT,                    -- raw systemd-analyze blame output
    raw_chain    TEXT                     -- raw systemd-analyze critical-chain output
);
```

### `bw_blame_entries`
One row per service per boot event.
```sql
CREATE TABLE bw_blame_entries (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    boot_id    INT NOT NULL REFERENCES bw_boots(id),
    service    VARCHAR(256) NOT NULL,
    time_s     FLOAT NOT NULL,
    INDEX (boot_id),
    INDEX (service)
);
```

### `bw_perf_stats`
One row per `perf stat` snapshot (collected alongside each boot or on-demand).
```sql
CREATE TABLE bw_perf_stats (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    device_id       INT NOT NULL REFERENCES bw_devices(id),
    revision_id     INT NOT NULL REFERENCES bw_sw_revisions(id),
    collected_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    duration_s      INT NOT NULL DEFAULT 10,   -- perf stat window
    cycles          BIGINT,
    instructions    BIGINT,
    ipc             FLOAT,                     -- instructions per cycle
    cache_misses    BIGINT,
    cache_refs      BIGINT,
    cache_miss_pct  FLOAT,
    branch_misses   BIGINT,
    branch_total    BIGINT,
    branch_miss_pct FLOAT,
    raw_output      TEXT                       -- full perf stat text output
);
```

### `bw_flamegraphs`
One row per on-demand flamegraph.
```sql
CREATE TABLE bw_flamegraphs (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    device_id    INT NOT NULL REFERENCES bw_devices(id),
    revision_id  INT NOT NULL REFERENCES bw_sw_revisions(id),
    generated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    duration_s   INT NOT NULL DEFAULT 15,
    svg_path     VARCHAR(512),    -- path to stored SVG file
    perf_data_path VARCHAR(512)   -- path to raw perf.data (optional)
);
```

---

## Collector Tools

### `tools/collect.py`
SSH into one device, collect boot data and perf stat, upload to server.

```
python3 tools/collect.py \
    --device 192.168.1.100 \
    --version 2.1.4 \
    --server 127.0.0.1 \
    --port 8080
```

**What it does:**
1. SSH connect to device
2. Run `systemd-analyze` → get total boot time
3. Run `systemd-analyze blame` → get per-service times
4. Run `systemd-analyze critical-chain` → get dependency chain
5. Run `perf stat -a sleep 10` → get CPU counters (10-second snapshot)
6. POST all data as JSON to `/api/boot` on the BootWatch server

**Arguments:**
| Arg | Default | Description |
|-----|---------|-------------|
| `--device` | required | Device IP |
| `--version` | auto-detect from `/etc/os-release` | SW revision string |
| `--server` | `127.0.0.1` | BootWatch server IP |
| `--port` | `8080` | BootWatch web port |
| `--ssh-user` | `root` | SSH username |
| `--ssh-port` | `22` | SSH port |
| `--ssh-key` | agent/default | Path to SSH private key |
| `--name` | `device` | Device name in DB |
| `--label` | empty | Device label in DB |
| `--skip-perf` | false | Skip perf stat collection |
| `--perf-duration` | `10` | perf stat window in seconds |

### `tools/collect-all.py`
Run `collect.py` in parallel threads across multiple devices. Same `--devices` / `--devices-file` pattern as CrashWeb.

```
python3 tools/collect-all.py --devices-file devices.txt --server 10.0.0.1
```

### `tools/install-hook.py`
SSH into a device and install a systemd unit that auto-reports boot data after every boot.

```
python3 tools/install-hook.py \
    --device 192.168.1.100 \
    --server 10.0.0.1 \
    --version-key BUILD_VERSION
```

**What it installs on the device:**
- `/usr/local/bin/bootwatch-report.sh` — shell script that runs `systemd-analyze`, `systemd-analyze blame`, `systemd-analyze critical-chain`, `perf stat -a sleep 10`, then POSTs JSON to the BootWatch server
- `/etc/systemd/system/bootwatch-report.service` — `Type=oneshot`, `After=multi-user.target`, `ExecStart=/usr/local/bin/bootwatch-report.sh`
- Enables and starts the service

**Requirements:** `curl` on device (for the POST).

### `tools/flamegraph.py`
On-demand flamegraph collector. SSH in, run `perf record -ag sleep 15`, fetch `perf.data`, generate SVG using `flamegraph.pl` (bundled in container), store SVG.

Called by the web server when user clicks "Profile Now" — not run directly by users.

---

## Server API (internal)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/boot` | POST | Receive boot data JSON from collect.py or boot hook |
| `/api/perf/stat` | POST | Receive perf stat JSON (included in /api/boot payload) |
| `/api/flamegraph/<device_id>` | POST | Trigger on-demand flamegraph for a device |
| `/api/flamegraph/<device_id>/status` | GET | Poll flamegraph generation status |

### `/api/boot` payload
```json
{
  "device_ip": "192.168.1.100",
  "device_name": "device-04",
  "device_label": "",
  "revision": "2.1.4",
  "source": "ssh_pull",
  "boot_time_s": 45.2,
  "blame": [
    {"service": "NetworkManager.service", "time_s": 18.4},
    {"service": "docker.service", "time_s": 9.1}
  ],
  "critical_chain": "graphical.target @45.2s\n  └─ ...",
  "perf_stat": {
    "duration_s": 10,
    "cycles": 48200000000,
    "instructions": 68400000000,
    "ipc": 1.42,
    "cache_misses": 980000,
    "cache_refs": 46700000,
    "cache_miss_pct": 2.1,
    "branch_misses": 380000,
    "branch_total": 47500000,
    "branch_miss_pct": 0.8,
    "raw_output": "..."
  }
}
```

---

## UI Design

### Theme
Tokyo Night — identical to CrashWeb:
- Canvas: `#1a1b26`
- Surface (cards): `#24283b`
- Surface hover: `#2f3354`
- Border: `#414868`
- Text: `#c0caf5`
- Muted: `#565f89`
- Accent: `#7aa2f7`
- Success (fast boot): `#9ece6a`
- Warning (slow): `#e0af68`
- Error (very slow): `#f7768e`

### Boot time color thresholds
| Color | Threshold | Meaning |
|-------|-----------|---------|
| `#9ece6a` (green) | < avg × 1.2 | Normal |
| `#e0af68` (amber) | avg × 1.2 – avg × 2.0 | Slow |
| `#f7768e` (red) | > avg × 2.0 | Very slow / regression |

### Layout
Fixed 220px sidebar (same pattern as CrashWeb) with icons + labels:
- ⚡ BootWatch (brand)
- 📊 Overview
- 💻 Devices
- 🏷 Firmware
- 📋 Boots
- 📦 Services
- 🔥 Perf

### Overview page
1. **Stat row** (4 cards with colored top bars): Devices · Boots Recorded · Slow Boots Today · Fleet Avg Boot Time
2. **Device cards grid**: one card per device showing latest boot time (color-coded), SW revision, last-seen time, 5-boot sparkline
3. **Bottom row** (2 columns):
   - Recent boots table: device / boot time / revision / time ago — clickable rows
   - Slowest services (fleet avg): service name + avg time + horizontal bar, sorted descending

### Boot detail page
3 panels:
1. **Blame table**: service name + time in seconds + relative bar, color-coded, sorted slowest-first. Click service → show last 20 journal lines for that service from boot.
2. **Boot time trend**: bar chart of last 10 boots for this device, color-coded by threshold, current boot outlined
3. **Critical chain**: preformatted text tree (output of `systemd-analyze critical-chain`), bottleneck service highlighted in red

Header: device name · boot #ID · revision · total time · delta vs device avg (▲ +Ns or ▼ -Ns)

### Firmware page
Table: revision / device count / avg boot time / min boot time / max boot time / boot count. Color-code avg time. Clicking revision → filtered Boots page for that revision.

### Services page
Table: service name / fleet avg time / worst device / worst time / present in N boots. Filter by revision. Click service → boots where that service was top-5 slowest.

### Perf page
Two sections:

**Stat counters:**
- Filter: device + revision
- 4 stat cards: IPC / cache-miss % / branch-miss % / cycles (with delta vs device avg)
- IPC trend bar chart across all snapshots for selected device, color-coded by revision

**Flamegraph:**
- "Profile Now" button — triggers `/api/flamegraph/<device_id>` POST, polls status, shows spinner
- Displays most recent flamegraph SVG inline (interactive — embedded `<object>` or inline SVG)
- Download SVG + Download perf.data buttons
- Last generated timestamp + revision label

---

## Project Structure

```
bootwatch/
├── docker-compose.yml
├── docker-compose-local.yml
├── docker-compose-production.yml
├── .env.example
├── web/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── app.py                  # Flask routes
│   ├── db.py                   # DB connection + helpers
│   ├── collector.py            # Flamegraph SSH + perf.data collection (called by app)
│   └── templates/
│       ├── base.html           # Sidebar, Tokyo Night CSS, shared layout
│       ├── overview.html
│       ├── boots.html
│       ├── boot_detail.html
│       ├── devices.html
│       ├── device_detail.html
│       ├── firmware.html
│       ├── services.html
│       └── perf.html
├── db/
│   └── init.sql                # CREATE TABLE statements
├── flamegraph/
│   └── flamegraph.pl           # Brendan Gregg's script (bundled)
├── tools/
│   ├── collect.py              # Single-device SSH collector
│   ├── collect-all.py          # Multi-device parallel collector
│   ├── install-hook.py         # Boot hook installer
│   └── devices.txt.example
└── docs/
    └── superpowers/
        └── specs/
            └── 2026-05-02-bootwatch-design.md
```

---

## Configuration (`.env`)

| Variable | Required | Description |
|----------|----------|-------------|
| `SECRET_KEY` | Yes | Flask secret key |
| `DB_HOST` | No | MariaDB host (default: `mariadb`) |
| `DB_USER` | No | DB user (default: `bootwatch`) |
| `DB_PASSWORD` | No | DB password |
| `DB_NAME` | No | DB name (default: `bootwatch`) |
| `FLAMEGRAPH_DIR` | No | Where SVGs are stored (default: `/data/flamegraphs`) |
| `SLOW_BOOT_MULTIPLIER` | No | Threshold for amber (default: `1.2`) |
| `VERY_SLOW_BOOT_MULTIPLIER` | No | Threshold for red (default: `2.0`) |

---

## What Does NOT Change vs CrashWeb

- Docker Compose file structure
- Traefik TLS setup
- SSH connection logic in collect.py (reuse paramiko pattern)
- Tokyo Night CSS (copy from CrashWeb base.html)
- Sidebar navigation HTML/CSS pattern
- `.env` configuration pattern
- `devices.txt` file format for collect-all.py
