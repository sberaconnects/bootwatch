# BootWatch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build BootWatch — a self-hosted Flask/MariaDB web UI for tracking embedded Linux device boot times, systemd service blame, and perf counters over SSH.

**Architecture:** Flask app + MariaDB in Docker Compose. Collector tools SSH into devices and POST JSON to the Flask API. All UI is server-rendered Jinja2 with inline Tokyo Night CSS — no JS frameworks. Flamegraph generation runs as a background thread triggered by a POST endpoint.

**Tech Stack:** Python 3 / Flask 2, MariaDB 10.6, Docker Compose, paramiko (SSH), Brendan Gregg's flamegraph.pl (Perl, bundled), pytest + Flask test client.

---

## File Map

| File | Purpose |
|------|---------|
| `docker-compose.yml` | Base services: mariadb + flask-web |
| `docker-compose-local.yml` | Override: expose port 8080, no Traefik |
| `docker-compose-production.yml` | Override: Traefik labels, HTTPS |
| `.env.example` | All env vars with defaults |
| `db/init.sql` | All 6 CREATE TABLE statements |
| `web/Dockerfile` | Python 3.11-slim, pip install, copy templates |
| `web/requirements.txt` | flask, pymysql, paramiko, cryptography |
| `web/db.py` | get_db(), query helpers (fetch_one, fetch_all, execute) |
| `web/app.py` | All Flask routes + API endpoints |
| `web/collector.py` | run_flamegraph_collection() — SSH + perf.data fetch + SVG gen |
| `web/templates/base.html` | Tokyo Night sidebar layout |
| `web/templates/overview.html` | Stat cards, device grid, recent boots, slowest services |
| `web/templates/boots.html` | Paginated boot list with filters |
| `web/templates/boot_detail.html` | Blame table + trend chart + critical chain |
| `web/templates/devices.html` | Device list table |
| `web/templates/device_detail.html` | Per-device history |
| `web/templates/firmware.html` | Per-revision stats table |
| `web/templates/services.html` | Fleet-wide service table |
| `web/templates/perf.html` | Perf stat cards + flamegraph UI |
| `flamegraph/flamegraph.pl` | Brendan Gregg's script (downloaded at build time) |
| `tools/collect.py` | Single-device SSH collector |
| `tools/collect-all.py` | Multi-device parallel wrapper |
| `tools/install-hook.py` | Boot hook installer |
| `tools/devices.txt.example` | Example device list |
| `tests/conftest.py` | pytest fixtures: Flask test client + in-memory SQLite |
| `tests/test_api.py` | POST /api/boot, /api/perf/stat tests |
| `tests/test_routes.py` | GET route smoke tests |

---

### Task 1: Project scaffold

**Files:**
- Create: `docker-compose.yml`
- Create: `docker-compose-local.yml`
- Create: `docker-compose-production.yml`
- Create: `.env.example`
- Create: `tools/devices.txt.example`

- [ ] **Step 1: Create docker-compose.yml**

```yaml
# docker-compose.yml
version: "3.9"
services:
  mariadb:
    image: mariadb:10.6
    restart: unless-stopped
    environment:
      MYSQL_ROOT_PASSWORD: ${DB_ROOT_PASSWORD:-rootpass}
      MYSQL_DATABASE: ${DB_NAME:-bootwatch}
      MYSQL_USER: ${DB_USER:-bootwatch}
      MYSQL_PASSWORD: ${DB_PASSWORD:-bootwatch}
    volumes:
      - mariadb_data:/var/lib/mysql
      - ./db/init.sql:/docker-entrypoint-initdb.d/init.sql:ro
    healthcheck:
      test: ["CMD", "healthcheck.sh", "--connect", "--innodb_initialized"]
      interval: 10s
      timeout: 5s
      retries: 5

  flask-web:
    build: ./web
    restart: unless-stopped
    depends_on:
      mariadb:
        condition: service_healthy
    environment:
      SECRET_KEY: ${SECRET_KEY:-change-me}
      DB_HOST: mariadb
      DB_USER: ${DB_USER:-bootwatch}
      DB_PASSWORD: ${DB_PASSWORD:-bootwatch}
      DB_NAME: ${DB_NAME:-bootwatch}
      FLAMEGRAPH_DIR: ${FLAMEGRAPH_DIR:-/data/flamegraphs}
      SLOW_BOOT_MULTIPLIER: ${SLOW_BOOT_MULTIPLIER:-1.2}
      VERY_SLOW_BOOT_MULTIPLIER: ${VERY_SLOW_BOOT_MULTIPLIER:-2.0}
    volumes:
      - flamegraph_data:/data/flamegraphs

volumes:
  mariadb_data:
  flamegraph_data:
```

- [ ] **Step 2: Create docker-compose-local.yml**

```yaml
# docker-compose-local.yml
version: "3.9"
services:
  flask-web:
    ports:
      - "8080:5000"
```

- [ ] **Step 3: Create docker-compose-production.yml**

```yaml
# docker-compose-production.yml
version: "3.9"
services:
  flask-web:
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.bootwatch.rule=Host(`${DOMAIN:-bootwatch.localhost}`)"
      - "traefik.http.routers.bootwatch.entrypoints=websecure"
      - "traefik.http.routers.bootwatch.tls.certresolver=letsencrypt"
      - "traefik.http.services.bootwatch.loadbalancer.server.port=5000"

  traefik:
    image: traefik:v3.0
    restart: unless-stopped
    command:
      - "--providers.docker=true"
      - "--providers.docker.exposedbydefault=false"
      - "--entrypoints.web.address=:80"
      - "--entrypoints.websecure.address=:443"
      - "--certificatesresolvers.letsencrypt.acme.email=${ACME_EMAIL}"
      - "--certificatesresolvers.letsencrypt.acme.storage=/acme/acme.json"
      - "--certificatesresolvers.letsencrypt.acme.tlschallenge=true"
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - traefik_acme:/acme

volumes:
  traefik_acme:
```

- [ ] **Step 4: Create .env.example**

```bash
# .env.example — copy to .env and fill in values
SECRET_KEY=change-me-to-random-string
DB_ROOT_PASSWORD=rootpass
DB_USER=bootwatch
DB_PASSWORD=bootwatch
DB_NAME=bootwatch
FLAMEGRAPH_DIR=/data/flamegraphs
SLOW_BOOT_MULTIPLIER=1.2
VERY_SLOW_BOOT_MULTIPLIER=2.0
# Production only:
DOMAIN=bootwatch.yourdomain.com
ACME_EMAIL=you@example.com
```

- [ ] **Step 5: Create tools/devices.txt.example**

```
# devices.txt — one device per line: IP [name] [label]
192.168.1.100 device-01 lab-prototype
192.168.1.101 device-02 qa-unit
```

- [ ] **Step 6: Commit**

```bash
git init
git add docker-compose.yml docker-compose-local.yml docker-compose-production.yml .env.example tools/devices.txt.example
git commit -m "feat: project scaffold — docker-compose + env template"
```

---

### Task 2: Database schema

**Files:**
- Create: `db/init.sql`

- [ ] **Step 1: Write init.sql**

```sql
-- db/init.sql
CREATE TABLE IF NOT EXISTS bw_devices (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(128) NOT NULL,
    label       VARCHAR(128) DEFAULT '',
    ip_addr     VARCHAR(64)  NOT NULL,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_ip (ip_addr)
);

CREATE TABLE IF NOT EXISTS bw_sw_revisions (
    id       INT AUTO_INCREMENT PRIMARY KEY,
    revision VARCHAR(128) NOT NULL,
    UNIQUE KEY uq_rev (revision)
);

CREATE TABLE IF NOT EXISTS bw_boots (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    device_id    INT NOT NULL,
    revision_id  INT NOT NULL,
    boot_time_s  FLOAT NOT NULL,
    collected_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    source       ENUM('ssh_pull','boot_hook') DEFAULT 'ssh_pull',
    raw_blame    TEXT,
    raw_chain    TEXT,
    FOREIGN KEY (device_id)   REFERENCES bw_devices(id),
    FOREIGN KEY (revision_id) REFERENCES bw_sw_revisions(id),
    INDEX idx_boots_device (device_id),
    INDEX idx_boots_revision (revision_id),
    INDEX idx_boots_collected (collected_at)
);

CREATE TABLE IF NOT EXISTS bw_blame_entries (
    id       INT AUTO_INCREMENT PRIMARY KEY,
    boot_id  INT NOT NULL,
    service  VARCHAR(256) NOT NULL,
    time_s   FLOAT NOT NULL,
    FOREIGN KEY (boot_id) REFERENCES bw_boots(id),
    INDEX idx_blame_boot    (boot_id),
    INDEX idx_blame_service (service)
);

CREATE TABLE IF NOT EXISTS bw_perf_stats (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    device_id       INT NOT NULL,
    revision_id     INT NOT NULL,
    collected_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    duration_s      INT NOT NULL DEFAULT 10,
    cycles          BIGINT,
    instructions    BIGINT,
    ipc             FLOAT,
    cache_misses    BIGINT,
    cache_refs      BIGINT,
    cache_miss_pct  FLOAT,
    branch_misses   BIGINT,
    branch_total    BIGINT,
    branch_miss_pct FLOAT,
    raw_output      TEXT,
    FOREIGN KEY (device_id)   REFERENCES bw_devices(id),
    FOREIGN KEY (revision_id) REFERENCES bw_sw_revisions(id),
    INDEX idx_perf_device (device_id)
);

CREATE TABLE IF NOT EXISTS bw_flamegraphs (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    device_id      INT NOT NULL,
    revision_id    INT NOT NULL,
    generated_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    duration_s     INT NOT NULL DEFAULT 15,
    svg_path       VARCHAR(512),
    perf_data_path VARCHAR(512),
    status         ENUM('pending','running','done','failed') DEFAULT 'pending',
    FOREIGN KEY (device_id)   REFERENCES bw_devices(id),
    FOREIGN KEY (revision_id) REFERENCES bw_sw_revisions(id),
    INDEX idx_fg_device (device_id)
);
```

Note: `bw_flamegraphs` has `status` column (not in spec but required for the polling API — added here, referenced in Task 11).

- [ ] **Step 2: Commit**

```bash
git add db/init.sql
git commit -m "feat: database schema — 6 tables"
```

---

### Task 3: Web Dockerfile + requirements.txt

**Files:**
- Create: `web/Dockerfile`
- Create: `web/requirements.txt`

- [ ] **Step 1: Create requirements.txt**

```
flask==3.0.3
pymysql==1.1.1
cryptography==42.0.8
paramiko==3.4.0
```

- [ ] **Step 2: Create Dockerfile**

```dockerfile
# web/Dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    linux-perf \
    perl \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download flamegraph.pl at build time
RUN mkdir -p /opt/flamegraph && \
    curl -fsSL https://raw.githubusercontent.com/brendangregg/FlameGraph/master/flamegraph.pl \
         -o /opt/flamegraph/flamegraph.pl && \
    chmod +x /opt/flamegraph/flamegraph.pl && \
    curl -fsSL https://raw.githubusercontent.com/brendangregg/FlameGraph/master/stackcollapse-perf.pl \
         -o /opt/flamegraph/stackcollapse-perf.pl && \
    chmod +x /opt/flamegraph/stackcollapse-perf.pl

COPY . .

ENV FLAMEGRAPH_BIN=/opt/flamegraph/flamegraph.pl
ENV STACKCOLLAPSE_BIN=/opt/flamegraph/stackcollapse-perf.pl

EXPOSE 5000
CMD ["python", "-m", "flask", "run", "--host=0.0.0.0"]
```

Note: `linux-perf` installs `perf` in the container for on-device flamegraph collection. `stackcollapse-perf.pl` is also needed to convert `perf.data` → folded stacks.

- [ ] **Step 3: Commit**

```bash
git add web/Dockerfile web/requirements.txt
git commit -m "feat: web Dockerfile and Python dependencies"
```

---

### Task 4: db.py — database helpers

**Files:**
- Create: `web/db.py`
- Create: `tests/conftest.py`
- Create: `tests/test_db.py`

- [ ] **Step 1: Write failing test**

```python
# tests/conftest.py
import pytest
import pymysql
import os

# Override to use test DB or SQLite-compatible dict cursor mock
# For simplicity, tests use a real MariaDB started by docker-compose.
# Set TEST_DB_HOST env var when running against a real DB.
# Tests that need DB use the `db_conn` fixture.

@pytest.fixture(scope="session")
def app():
    os.environ.setdefault("SECRET_KEY", "test")
    os.environ.setdefault("DB_HOST", os.environ.get("TEST_DB_HOST", "127.0.0.1"))
    os.environ.setdefault("DB_USER", "bootwatch")
    os.environ.setdefault("DB_PASSWORD", "bootwatch")
    os.environ.setdefault("DB_NAME", "bootwatch")
    os.environ.setdefault("FLAMEGRAPH_DIR", "/tmp/test_flamegraphs")
    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    return app

@pytest.fixture
def client(app):
    return app.test_client()
```

```python
# tests/test_db.py
from db import get_or_create_device, get_or_create_revision

def test_get_or_create_device_returns_id(app):
    with app.app_context():
        device_id = get_or_create_device("192.168.99.1", "test-dev", "test-label")
        assert isinstance(device_id, int)
        assert device_id > 0
        # second call returns same id
        device_id2 = get_or_create_device("192.168.99.1", "test-dev", "test-label")
        assert device_id == device_id2

def test_get_or_create_revision_returns_id(app):
    with app.app_context():
        rev_id = get_or_create_revision("v1.0.0-test")
        assert isinstance(rev_id, int)
        rev_id2 = get_or_create_revision("v1.0.0-test")
        assert rev_id == rev_id2
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/sbera/git/personal/bootwatch
# Start DB first: docker compose -f docker-compose.yml -f docker-compose-local.yml up -d mariadb
cd web && python -m pytest ../tests/test_db.py -v
```

Expected: `ModuleNotFoundError: No module named 'db'` or `ImportError`

- [ ] **Step 3: Write db.py**

```python
# web/db.py
import os
import pymysql
import pymysql.cursors
from flask import g

def get_db():
    if 'db' not in g:
        g.db = pymysql.connect(
            host=os.environ.get('DB_HOST', 'mariadb'),
            user=os.environ.get('DB_USER', 'bootwatch'),
            password=os.environ.get('DB_PASSWORD', 'bootwatch'),
            database=os.environ.get('DB_NAME', 'bootwatch'),
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True,
        )
    return g.db

def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def fetch_one(sql, args=()):
    db = get_db()
    with db.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchone()

def fetch_all(sql, args=()):
    db = get_db()
    with db.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchall()

def execute(sql, args=()):
    db = get_db()
    with db.cursor() as cur:
        cur.execute(sql, args)
        return cur.lastrowid

def get_or_create_device(ip_addr, name, label=''):
    row = fetch_one('SELECT id FROM bw_devices WHERE ip_addr = %s', (ip_addr,))
    if row:
        return row['id']
    return execute(
        'INSERT INTO bw_devices (ip_addr, name, label) VALUES (%s, %s, %s)',
        (ip_addr, name, label)
    )

def get_or_create_revision(revision):
    row = fetch_one('SELECT id FROM bw_sw_revisions WHERE revision = %s', (revision,))
    if row:
        return row['id']
    return execute('INSERT INTO bw_sw_revisions (revision) VALUES (%s)', (revision,))
```

- [ ] **Step 4: Run tests**

```bash
cd web && python -m pytest ../tests/test_db.py -v
```

Expected: PASS (requires running MariaDB — `docker compose ... up -d mariadb`)

- [ ] **Step 5: Commit**

```bash
git add web/db.py tests/conftest.py tests/test_db.py
git commit -m "feat: db.py helpers — get_db, fetch helpers, get_or_create_device/revision"
```

---

### Task 5: app.py skeleton + POST /api/boot

**Files:**
- Create: `web/app.py`
- Create: `tests/test_api.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_api.py
import json

BOOT_PAYLOAD = {
    "device_ip": "192.168.99.2",
    "device_name": "test-device",
    "device_label": "",
    "revision": "v-test-1",
    "source": "ssh_pull",
    "boot_time_s": 32.5,
    "blame": [
        {"service": "NetworkManager.service", "time_s": 12.0},
        {"service": "docker.service",          "time_s": 6.5},
    ],
    "critical_chain": "multi-user.target @32.5s\n  └─ NetworkManager.service @20s",
    "perf_stat": {
        "duration_s": 10,
        "cycles": 10000000,
        "instructions": 14200000,
        "ipc": 1.42,
        "cache_misses": 50000,
        "cache_refs": 2380000,
        "cache_miss_pct": 2.1,
        "branch_misses": 19000,
        "branch_total": 2375000,
        "branch_miss_pct": 0.8,
        "raw_output": "perf stat output here"
    }
}

def test_post_boot_returns_201(client):
    resp = client.post(
        '/api/boot',
        data=json.dumps(BOOT_PAYLOAD),
        content_type='application/json'
    )
    assert resp.status_code == 201
    data = resp.get_json()
    assert 'boot_id' in data

def test_post_boot_missing_required_field(client):
    bad = {k: v for k, v in BOOT_PAYLOAD.items() if k != 'boot_time_s'}
    resp = client.post('/api/boot', data=json.dumps(bad), content_type='application/json')
    assert resp.status_code == 400

def test_post_boot_without_perf_stat(client):
    payload = dict(BOOT_PAYLOAD)
    del payload['perf_stat']
    resp = client.post('/api/boot', data=json.dumps(payload), content_type='application/json')
    assert resp.status_code == 201
```

- [ ] **Step 2: Run to verify failure**

```bash
cd web && python -m pytest ../tests/test_api.py -v
```

Expected: FAIL — `create_app` not defined

- [ ] **Step 3: Write app.py with create_app and /api/boot**

```python
# web/app.py
import os
import json
import threading
from flask import Flask, request, jsonify, render_template, redirect, url_for, abort
from db import (close_db, fetch_one, fetch_all, execute,
                get_or_create_device, get_or_create_revision)

def create_app():
    app = Flask(__name__)
    app.secret_key = os.environ.get('SECRET_KEY', 'dev')
    app.teardown_appcontext(close_db)

    # ---------- API ----------

    @app.route('/api/boot', methods=['POST'])
    def api_boot():
        data = request.get_json(silent=True) or {}
        required = ['device_ip', 'device_name', 'revision', 'boot_time_s', 'blame']
        missing = [f for f in required if f not in data]
        if missing:
            return jsonify(error=f"missing fields: {missing}"), 400

        device_id  = get_or_create_device(data['device_ip'], data['device_name'], data.get('device_label', ''))
        revision_id = get_or_create_revision(data['revision'])

        boot_id = execute(
            'INSERT INTO bw_boots (device_id, revision_id, boot_time_s, source, raw_blame, raw_chain) '
            'VALUES (%s, %s, %s, %s, %s, %s)',
            (device_id, revision_id, data['boot_time_s'],
             data.get('source', 'ssh_pull'),
             data.get('raw_blame', ''),
             data.get('critical_chain', ''))
        )

        for entry in data.get('blame', []):
            execute(
                'INSERT INTO bw_blame_entries (boot_id, service, time_s) VALUES (%s, %s, %s)',
                (boot_id, entry['service'], entry['time_s'])
            )

        ps = data.get('perf_stat')
        if ps:
            execute(
                'INSERT INTO bw_perf_stats '
                '(device_id, revision_id, duration_s, cycles, instructions, ipc, '
                ' cache_misses, cache_refs, cache_miss_pct, '
                ' branch_misses, branch_total, branch_miss_pct, raw_output) '
                'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                (device_id, revision_id,
                 ps.get('duration_s', 10),
                 ps.get('cycles'), ps.get('instructions'), ps.get('ipc'),
                 ps.get('cache_misses'), ps.get('cache_refs'), ps.get('cache_miss_pct'),
                 ps.get('branch_misses'), ps.get('branch_total'), ps.get('branch_miss_pct'),
                 ps.get('raw_output', ''))
            )

        return jsonify(boot_id=boot_id), 201

    # ---------- Pages (stubs — filled in later tasks) ----------

    @app.route('/')
    def overview():
        return render_template('overview.html')

    @app.route('/boots')
    def boots():
        return render_template('boots.html', boots=[], total=0, page=1, per_page=50)

    @app.route('/boot/<int:boot_id>')
    def boot_detail(boot_id):
        boot = fetch_one('SELECT * FROM bw_boots WHERE id = %s', (boot_id,))
        if not boot:
            abort(404)
        return render_template('boot_detail.html', boot=boot, blame=[], trend=[])

    @app.route('/devices')
    def devices():
        return render_template('devices.html', devices=[])

    @app.route('/device/<int:device_id>')
    def device_detail(device_id):
        device = fetch_one('SELECT * FROM bw_devices WHERE id = %s', (device_id,))
        if not device:
            abort(404)
        return render_template('device_detail.html', device=device, boots=[])

    @app.route('/firmware')
    def firmware():
        return render_template('firmware.html', revisions=[])

    @app.route('/services')
    def services():
        return render_template('services.html', services=[])

    @app.route('/perf')
    def perf():
        return render_template('perf.html', stats=[], flamegraph=None)

    @app.route('/api/flamegraph/<int:device_id>', methods=['POST'])
    def api_flamegraph_trigger(device_id):
        device = fetch_one('SELECT * FROM bw_devices WHERE id = %s', (device_id,))
        if not device:
            return jsonify(error='device not found'), 404
        revision = request.get_json(silent=True) or {}
        revision_str = revision.get('revision', 'unknown')
        revision_id = get_or_create_revision(revision_str)
        fg_id = execute(
            'INSERT INTO bw_flamegraphs (device_id, revision_id, status) VALUES (%s, %s, %s)',
            (device_id, revision_id, 'pending')
        )
        from collector import start_flamegraph_job
        threading.Thread(target=start_flamegraph_job, args=(fg_id, device, revision_str), daemon=True).start()
        return jsonify(flamegraph_id=fg_id), 202

    @app.route('/api/flamegraph/<int:device_id>/status')
    def api_flamegraph_status(device_id):
        fg = fetch_one(
            'SELECT id, status, svg_path, generated_at FROM bw_flamegraphs '
            'WHERE device_id = %s ORDER BY generated_at DESC LIMIT 1',
            (device_id,)
        )
        if not fg:
            return jsonify(status='none'), 200
        return jsonify(
            flamegraph_id=fg['id'],
            status=fg['status'],
            svg_path=fg['svg_path'],
            generated_at=str(fg['generated_at']) if fg['generated_at'] else None
        )

    return app


if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', debug=True)
```

- [ ] **Step 4: Run API tests**

```bash
cd web && python -m pytest ../tests/test_api.py -v
```

Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add web/app.py tests/test_api.py
git commit -m "feat: Flask app skeleton + POST /api/boot endpoint"
```

---

### Task 6: base.html — Tokyo Night sidebar

**Files:**
- Create: `web/templates/base.html`
- Create: `tests/test_routes.py`

- [ ] **Step 1: Write route smoke tests**

```python
# tests/test_routes.py

def test_overview_200(client):
    resp = client.get('/')
    assert resp.status_code == 200

def test_boots_200(client):
    resp = client.get('/boots')
    assert resp.status_code == 200

def test_devices_200(client):
    resp = client.get('/devices')
    assert resp.status_code == 200

def test_firmware_200(client):
    resp = client.get('/firmware')
    assert resp.status_code == 200

def test_services_200(client):
    resp = client.get('/services')
    assert resp.status_code == 200

def test_perf_200(client):
    resp = client.get('/perf')
    assert resp.status_code == 200

def test_boot_detail_404(client):
    resp = client.get('/boot/999999')
    assert resp.status_code == 404

def test_device_detail_404(client):
    resp = client.get('/device/999999')
    assert resp.status_code == 404
```

- [ ] **Step 2: Run to verify failure**

```bash
cd web && python -m pytest ../tests/test_routes.py -v
```

Expected: FAIL — `TemplateNotFound`

- [ ] **Step 3: Create base.html**

```html
{# web/templates/base.html #}
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}BootWatch{% endblock %}</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
           background: #1a1b26; color: #c0caf5; min-height: 100vh; display: flex; }

    /* Sidebar */
    .sidebar { width: 220px; background: #16161e; position: fixed; top: 0; left: 0;
               height: 100vh; display: flex; flex-direction: column;
               border-right: 1px solid #414868; z-index: 100; }
    .sidebar-brand { display: block; padding: 20px 16px 16px;
                     font-size: 15px; font-weight: 700; color: #7aa2f7;
                     text-decoration: none; border-bottom: 1px solid #414868; }
    .sidebar-nav { flex: 1; padding: 8px 0; overflow-y: auto; }
    .sidebar-nav a { display: flex; align-items: center; gap: 10px;
                     padding: 9px 16px; color: #565f89; text-decoration: none;
                     font-size: 13px; transition: background 0.15s, color 0.15s; }
    .sidebar-nav a:hover { background: #1f2335; color: #c0caf5; }
    .sidebar-nav a.active { background: #1f2335; color: #7aa2f7; font-weight: 600; }
    .sidebar-footer { padding: 12px 16px; font-size: 10px; color: #414868;
                      border-top: 1px solid #414868; }

    /* Main */
    .main { margin-left: 220px; padding: 28px 32px; width: calc(100% - 220px); }

    /* Cards */
    .card { background: #24283b; border: 1px solid #414868; border-radius: 8px;
            padding: 16px; margin-bottom: 16px; }
    .card > h2 { font-size: 11px; text-transform: uppercase; letter-spacing: 0.8px;
                 color: #565f89; margin-bottom: 12px; }
    .card-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
                 gap: 12px; margin-bottom: 16px; }

    /* Stat cards */
    .stat-card { background: #24283b; border: 1px solid #414868; border-radius: 8px;
                 padding: 16px; position: relative; overflow: hidden; }
    .stat-card::before { content: ''; position: absolute; top: 0; left: 0; right: 0;
                         height: 3px; background: var(--accent-bar, #7aa2f7); }
    .stat-card .number { font-size: 36px; font-weight: 700; color: #c0caf5; line-height: 1; }
    .stat-card .label  { font-size: 10px; text-transform: uppercase; letter-spacing: 0.6px;
                         color: #565f89; margin-top: 6px; }
    .stat-card .delta  { font-size: 11px; margin-top: 4px; }

    /* Tables */
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th { text-align: left; font-size: 10px; text-transform: uppercase; letter-spacing: 0.6px;
         color: #565f89; padding: 8px 10px; border-bottom: 1px solid #414868; }
    td { padding: 9px 10px; border-bottom: 1px solid #2f3354; color: #c0caf5; }
    tr:hover td { background: #1f2335; }
    tr:last-child td { border-bottom: none; }
    a { color: #7aa2f7; text-decoration: none; }
    a:hover { text-decoration: underline; }

    /* Page header */
    .page-header { margin-bottom: 24px; }
    .page-header h1 { font-size: 22px; font-weight: 700; color: #c0caf5; }
    .page-header p  { color: #565f89; font-size: 13px; margin-top: 4px; }

    /* Badges */
    .badge { display: inline-block; padding: 2px 8px; border-radius: 12px;
             font-size: 11px; font-weight: 600; }
    .badge-green  { background: #1e2d1e; color: #9ece6a; border: 1px solid #3d6b3d; }
    .badge-amber  { background: #2d2619; color: #e0af68; border: 1px solid #6b5219; }
    .badge-red    { background: #2d1a1e; color: #f7768e; border: 1px solid #6b2535; }
    .badge-blue   { background: #1a2035; color: #7aa2f7; border: 1px solid #2d4080; }

    /* Horizontal bar */
    .bar-wrap { background: #1a1b26; border-radius: 3px; height: 6px; overflow: hidden; }
    .bar-fill  { height: 100%; border-radius: 3px; background: #7aa2f7; }

    /* Filters row */
    .filters { display: flex; gap: 10px; align-items: flex-end; margin-bottom: 16px; flex-wrap: wrap; }
    .filter-group label { display: block; font-size: 10px; text-transform: uppercase;
                          letter-spacing: 0.5px; color: #565f89; margin-bottom: 4px; }
    .filter-group select, .filter-group input {
      background: #24283b; border: 1px solid #414868; border-radius: 4px;
      padding: 5px 10px; color: #c0caf5; font-size: 12px; }
    .btn { display: inline-block; padding: 6px 14px; border-radius: 4px; font-size: 12px;
           font-weight: 600; cursor: pointer; border: none; text-decoration: none; }
    .btn-primary { background: #7aa2f7; color: #1a1b26; }
    .btn-secondary { background: #2f3354; color: #c0caf5; border: 1px solid #414868; }
  </style>
  {% block head %}{% endblock %}
</head>
<body>
<aside class="sidebar">
  <a class="sidebar-brand" href="{{ url_for('overview') }}">⚡ BootWatch</a>
  <nav class="sidebar-nav">
    <a href="{{ url_for('overview') }}"
       class="{{ 'active' if request.endpoint == 'overview' else '' }}">📊 Overview</a>
    <a href="{{ url_for('devices') }}"
       class="{{ 'active' if request.endpoint in ('devices','device_detail') else '' }}">💻 Devices</a>
    <a href="{{ url_for('firmware') }}"
       class="{{ 'active' if request.endpoint == 'firmware' else '' }}">🏷 Firmware</a>
    <a href="{{ url_for('boots') }}"
       class="{{ 'active' if request.endpoint in ('boots','boot_detail') else '' }}">📋 Boots</a>
    <a href="{{ url_for('services') }}"
       class="{{ 'active' if request.endpoint == 'services' else '' }}">📦 Services</a>
    <a href="{{ url_for('perf') }}"
       class="{{ 'active' if request.endpoint == 'perf' else '' }}">🔥 Perf</a>
  </nav>
  <div class="sidebar-footer">BootWatch</div>
</aside>
<div class="main">
  {% block content %}{% endblock %}
</div>
{% block scripts %}{% endblock %}
</body>
</html>
```

- [ ] **Step 4: Create stub templates for all pages**

Create these files, each with minimal content so route tests pass:

`web/templates/overview.html`:
```html
{% extends "base.html" %}
{% block title %}Overview — BootWatch{% endblock %}
{% block content %}
<div class="page-header"><h1>Overview</h1></div>
{% endblock %}
```

`web/templates/boots.html`:
```html
{% extends "base.html" %}
{% block title %}Boots — BootWatch{% endblock %}
{% block content %}
<div class="page-header"><h1>Boots</h1></div>
{% endblock %}
```

`web/templates/boot_detail.html`:
```html
{% extends "base.html" %}
{% block title %}Boot #{{ boot.id }} — BootWatch{% endblock %}
{% block content %}
<div class="page-header"><h1>Boot #{{ boot.id }}</h1></div>
{% endblock %}
```

`web/templates/devices.html`:
```html
{% extends "base.html" %}
{% block title %}Devices — BootWatch{% endblock %}
{% block content %}
<div class="page-header"><h1>Devices</h1></div>
{% endblock %}
```

`web/templates/device_detail.html`:
```html
{% extends "base.html" %}
{% block title %}{{ device.name }} — BootWatch{% endblock %}
{% block content %}
<div class="page-header"><h1>{{ device.name }}</h1></div>
{% endblock %}
```

`web/templates/firmware.html`:
```html
{% extends "base.html" %}
{% block title %}Firmware — BootWatch{% endblock %}
{% block content %}
<div class="page-header"><h1>Firmware</h1></div>
{% endblock %}
```

`web/templates/services.html`:
```html
{% extends "base.html" %}
{% block title %}Services — BootWatch{% endblock %}
{% block content %}
<div class="page-header"><h1>Services</h1></div>
{% endblock %}
```

`web/templates/perf.html`:
```html
{% extends "base.html" %}
{% block title %}Perf — BootWatch{% endblock %}
{% block content %}
<div class="page-header"><h1>Perf</h1></div>
{% endblock %}
```

- [ ] **Step 5: Run route tests**

```bash
cd web && python -m pytest ../tests/test_routes.py -v
```

Expected: PASS (8 tests)

- [ ] **Step 6: Commit**

```bash
git add web/templates/
git commit -m "feat: base.html Tokyo Night sidebar + stub templates for all pages"
```

---

### Task 7: collector.py — flamegraph SSH worker

**Files:**
- Create: `web/collector.py`

No unit test here — paramiko SSH is an integration concern. Manual test in Task 13 (perf page).

- [ ] **Step 1: Create collector.py**

```python
# web/collector.py
import os
import subprocess
import tempfile
import paramiko
from db import execute, fetch_one

FLAMEGRAPH_BIN   = os.environ.get('FLAMEGRAPH_BIN',   '/opt/flamegraph/flamegraph.pl')
STACKCOLLAPSE_BIN = os.environ.get('STACKCOLLAPSE_BIN', '/opt/flamegraph/stackcollapse-perf.pl')
FLAMEGRAPH_DIR   = os.environ.get('FLAMEGRAPH_DIR',   '/data/flamegraphs')


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


def start_flamegraph_job(fg_id, device, revision_str, duration_s=15):
    """
    Runs in a background thread. SSHes to device, runs perf record,
    fetches perf.data, generates flamegraph SVG, updates bw_flamegraphs row.
    """
    execute('UPDATE bw_flamegraphs SET status=%s WHERE id=%s', ('running', fg_id))

    try:
        ssh = _ssh_connect(device)
        remote_perf = f'/tmp/bw-perf-{fg_id}.data'

        # Run perf record on device
        cmd = f'perf record -ag -o {remote_perf} sleep {duration_s}'
        stdin, stdout, stderr = ssh.exec_command(cmd, timeout=duration_s + 30)
        stdout.channel.recv_exit_status()  # wait

        # Fetch perf.data
        os.makedirs(FLAMEGRAPH_DIR, exist_ok=True)
        local_perf = os.path.join(FLAMEGRAPH_DIR, f'perf-{fg_id}.data')
        sftp = ssh.open_sftp()
        sftp.get(remote_perf, local_perf)
        sftp.close()
        ssh.exec_command(f'rm -f {remote_perf}')
        ssh.close()

        # Generate folded stacks
        folded = subprocess.check_output(
            ['perl', STACKCOLLAPSE_BIN, '--pid', '--kernel'],
            stdin=open(f'/proc/{os.getpid()}/fd/0', 'rb'),  # dummy — use pipe below
        )
        # Use shell pipeline: perf script | stackcollapse-perf.pl | flamegraph.pl > out.svg
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

    except Exception as exc:
        execute('UPDATE bw_flamegraphs SET status=%s WHERE id=%s', ('failed', fg_id))
        raise
```

- [ ] **Step 2: Commit**

```bash
git add web/collector.py
git commit -m "feat: collector.py flamegraph SSH worker"
```

---

### Task 8: Overview page — real data queries

**Files:**
- Modify: `web/app.py` (overview route)
- Modify: `web/templates/overview.html`

- [ ] **Step 1: Update overview route in app.py**

Replace the stub `overview()` function with:

```python
@app.route('/')
def overview():
    # Stat row
    device_count = (fetch_one('SELECT COUNT(*) AS n FROM bw_devices') or {}).get('n', 0)
    boot_count   = (fetch_one('SELECT COUNT(*) AS n FROM bw_boots') or {}).get('n', 0)
    slow_mult    = float(os.environ.get('VERY_SLOW_BOOT_MULTIPLIER', 2.0))
    today_slow   = (fetch_one(
        'SELECT COUNT(*) AS n FROM bw_boots b '
        'JOIN (SELECT device_id, AVG(boot_time_s) AS avg_t FROM bw_boots GROUP BY device_id) a '
        '  ON b.device_id = a.device_id '
        'WHERE DATE(b.collected_at) = CURDATE() AND b.boot_time_s > a.avg_t * %s',
        (slow_mult,)
    ) or {}).get('n', 0)
    fleet_avg = (fetch_one('SELECT AVG(boot_time_s) AS a FROM bw_boots') or {}).get('a')

    # Device cards with last boot + 5-boot sparkline
    devices = fetch_all('''
        SELECT d.id, d.name, d.label,
               b.boot_time_s AS last_boot,
               b.collected_at AS last_seen,
               r.revision AS last_revision
        FROM bw_devices d
        LEFT JOIN bw_boots b ON b.id = (
            SELECT id FROM bw_boots WHERE device_id = d.id ORDER BY collected_at DESC LIMIT 1
        )
        LEFT JOIN bw_sw_revisions r ON r.id = b.revision_id
        ORDER BY d.name
    ''')

    for dev in devices:
        dev['sparkline'] = fetch_all(
            'SELECT boot_time_s FROM bw_boots WHERE device_id = %s ORDER BY collected_at DESC LIMIT 5',
            (dev['id'],)
        )
        dev['avg_boot'] = (fetch_one(
            'SELECT AVG(boot_time_s) AS a FROM bw_boots WHERE device_id = %s', (dev['id'],)
        ) or {}).get('a')

    # Recent boots
    recent = fetch_all('''
        SELECT b.id, d.name AS device_name, b.boot_time_s, r.revision, b.collected_at
        FROM bw_boots b
        JOIN bw_devices d ON d.id = b.device_id
        JOIN bw_sw_revisions r ON r.id = b.revision_id
        ORDER BY b.collected_at DESC LIMIT 10
    ''')

    # Slowest services fleet-wide
    slow_services = fetch_all('''
        SELECT service, AVG(time_s) AS avg_time, COUNT(*) AS n_boots
        FROM bw_blame_entries
        GROUP BY service
        ORDER BY avg_time DESC LIMIT 10
    ''')
    max_svc_time = slow_services[0]['avg_time'] if slow_services else 1

    return render_template('overview.html',
        device_count=device_count, boot_count=boot_count,
        today_slow=today_slow, fleet_avg=fleet_avg,
        devices=devices, recent=recent,
        slow_services=slow_services, max_svc_time=max_svc_time,
        slow_mult=float(os.environ.get('SLOW_BOOT_MULTIPLIER', 1.2)),
        very_slow_mult=slow_mult,
    )
```

- [ ] **Step 2: Update overview.html**

```html
{% extends "base.html" %}
{% block title %}Overview — BootWatch{% endblock %}
{% block content %}
<div class="page-header">
  <h1>Overview</h1>
  <p>Fleet boot health at a glance</p>
</div>

{# Stat cards #}
<div class="card-grid" style="grid-template-columns:repeat(4,1fr)">
  <div class="stat-card" style="--accent-bar:#7aa2f7">
    <div class="number">{{ device_count }}</div>
    <div class="label">Devices</div>
  </div>
  <div class="stat-card" style="--accent-bar:#9ece6a">
    <div class="number">{{ boot_count }}</div>
    <div class="label">Boots Recorded</div>
  </div>
  <div class="stat-card" style="--accent-bar:#f7768e">
    <div class="number">{{ today_slow }}</div>
    <div class="label">Slow Boots Today</div>
  </div>
  <div class="stat-card" style="--accent-bar:#e0af68">
    <div class="number">{{ "%.1f"|format(fleet_avg) if fleet_avg else "—" }}s</div>
    <div class="label">Fleet Avg Boot</div>
  </div>
</div>

{# Device cards grid #}
<div class="card">
  <h2>Devices</h2>
  <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:10px">
  {% for dev in devices %}
    {% set color = '#9ece6a' if dev.last_boot and dev.avg_boot and dev.last_boot < dev.avg_boot * slow_mult
                  else '#e0af68' if dev.last_boot and dev.avg_boot and dev.last_boot < dev.avg_boot * very_slow_mult
                  else '#f7768e' if dev.last_boot else '#565f89' %}
    <a href="{{ url_for('device_detail', device_id=dev.id) }}" style="text-decoration:none">
      <div style="background:#1a1b26;border:1px solid #414868;border-radius:6px;padding:12px;
                  border-top:3px solid {{ color }}">
        <div style="font-weight:600;color:#c0caf5;font-size:13px">{{ dev.name }}</div>
        {% if dev.label %}<div style="font-size:10px;color:#565f89">{{ dev.label }}</div>{% endif %}
        <div style="font-size:20px;font-weight:700;color:{{ color }};margin:8px 0">
          {{ "%.1f"|format(dev.last_boot) if dev.last_boot else "—" }}s
        </div>
        <div style="font-size:10px;color:#565f89">{{ dev.last_revision or "—" }}</div>
        {# Sparkline #}
        {% if dev.sparkline %}
        <div style="display:flex;align-items:flex-end;gap:2px;height:20px;margin-top:6px">
          {% set max_spark = dev.sparkline | map(attribute='boot_time_s') | max %}
          {% for s in dev.sparkline | reverse %}
          <div style="flex:1;background:{{ color }};opacity:0.7;border-radius:1px;
                      height:{{ ((s.boot_time_s / max_spark) * 100)|int }}%"></div>
          {% endfor %}
        </div>
        {% endif %}
      </div>
    </a>
  {% else %}
    <p style="color:#565f89;grid-column:1/-1">No devices yet. Run collect.py to add one.</p>
  {% endfor %}
  </div>
</div>

{# Bottom row #}
<div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
  <div class="card">
    <h2>Recent Boots</h2>
    <table>
      <thead><tr>
        <th>Device</th><th>Boot Time</th><th>Revision</th><th>When</th>
      </tr></thead>
      <tbody>
      {% for b in recent %}
        <tr style="cursor:pointer" onclick="window.location='{{ url_for('boot_detail', boot_id=b.id) }}'">
          <td>{{ b.device_name }}</td>
          <td>{{ "%.1f"|format(b.boot_time_s) }}s</td>
          <td><span class="badge badge-blue">{{ b.revision }}</span></td>
          <td style="color:#565f89;font-size:11px">{{ b.collected_at }}</td>
        </tr>
      {% else %}
        <tr><td colspan="4" style="color:#565f89;text-align:center;padding:20px">No boots recorded yet</td></tr>
      {% endfor %}
      </tbody>
    </table>
  </div>

  <div class="card">
    <h2>Slowest Services (fleet avg)</h2>
    <div>
    {% for svc in slow_services %}
      <div style="margin-bottom:8px">
        <div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:3px">
          <span style="color:#c0caf5">{{ svc.service }}</span>
          <span style="color:#e0af68">{{ "%.2f"|format(svc.avg_time) }}s</span>
        </div>
        <div class="bar-wrap">
          <div class="bar-fill" style="width:{{ ((svc.avg_time/max_svc_time)*100)|int }}%;background:#e0af68"></div>
        </div>
      </div>
    {% else %}
      <p style="color:#565f89;font-size:13px">No service data yet</p>
    {% endfor %}
    </div>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 3: Run route test still passes**

```bash
cd web && python -m pytest ../tests/test_routes.py::test_overview_200 -v
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add web/app.py web/templates/overview.html
git commit -m "feat: overview page with real data queries"
```


---

### Task 9: Boots list page

**Files:**
- Modify: `web/app.py` (boots route)
- Modify: `web/templates/boots.html`

- [ ] **Step 1: Update boots route in app.py**

Replace stub `boots()`:

```python
@app.route('/boots')
def boots():
    page     = max(1, request.args.get('page', 1, type=int))
    per_page = 50
    device_f  = request.args.get('device', '')
    rev_f     = request.args.get('revision', '')
    date_f    = request.args.get('date', '')

    where_clauses = []
    args = []
    if device_f:
        where_clauses.append('d.name = %s')
        args.append(device_f)
    if rev_f:
        where_clauses.append('r.revision = %s')
        args.append(rev_f)
    if date_f:
        where_clauses.append('DATE(b.collected_at) = %s')
        args.append(date_f)

    where = ('WHERE ' + ' AND '.join(where_clauses)) if where_clauses else ''

    total = (fetch_one(
        f'SELECT COUNT(*) AS n FROM bw_boots b '
        f'JOIN bw_devices d ON d.id=b.device_id '
        f'JOIN bw_sw_revisions r ON r.id=b.revision_id {where}',
        args
    ) or {}).get('n', 0)

    offset = (page - 1) * per_page
    boots_list = fetch_all(
        f'SELECT b.id, d.name AS device_name, b.boot_time_s, r.revision, '
        f'b.collected_at, b.source '
        f'FROM bw_boots b '
        f'JOIN bw_devices d ON d.id=b.device_id '
        f'JOIN bw_sw_revisions r ON r.id=b.revision_id '
        f'{where} ORDER BY b.collected_at DESC LIMIT %s OFFSET %s',
        args + [per_page, offset]
    )

    # Per-device avg for color coding
    avgs = {r['device_id']: r['avg_t'] for r in fetch_all(
        'SELECT device_id, AVG(boot_time_s) AS avg_t FROM bw_boots GROUP BY device_id'
    )}

    all_devices   = fetch_all('SELECT DISTINCT name FROM bw_devices ORDER BY name')
    all_revisions = fetch_all('SELECT revision FROM bw_sw_revisions ORDER BY revision')

    slow_mult      = float(os.environ.get('SLOW_BOOT_MULTIPLIER', 1.2))
    very_slow_mult = float(os.environ.get('VERY_SLOW_BOOT_MULTIPLIER', 2.0))

    return render_template('boots.html',
        boots=boots_list, total=total, page=page, per_page=per_page,
        device_f=device_f, rev_f=rev_f, date_f=date_f,
        all_devices=all_devices, all_revisions=all_revisions,
        avgs=avgs, slow_mult=slow_mult, very_slow_mult=very_slow_mult,
    )
```

- [ ] **Step 2: Update boots.html**

```html
{% extends "base.html" %}
{% block title %}Boots — BootWatch{% endblock %}
{% block content %}
<div class="page-header">
  <h1>Boots</h1>
  <p>{{ total }} boot events recorded</p>
</div>

<form method="get" class="filters">
  <div class="filter-group">
    <label>Device</label>
    <select name="device" onchange="this.form.submit()">
      <option value="">All</option>
      {% for d in all_devices %}
        <option value="{{ d.name }}" {{ 'selected' if device_f == d.name }}>{{ d.name }}</option>
      {% endfor %}
    </select>
  </div>
  <div class="filter-group">
    <label>Revision</label>
    <select name="revision" onchange="this.form.submit()">
      <option value="">All</option>
      {% for r in all_revisions %}
        <option value="{{ r.revision }}" {{ 'selected' if rev_f == r.revision }}>{{ r.revision }}</option>
      {% endfor %}
    </select>
  </div>
  <div class="filter-group">
    <label>Date</label>
    <input type="date" name="date" value="{{ date_f }}" onchange="this.form.submit()">
  </div>
</form>

<div class="card" style="padding:0">
  <table>
    <thead><tr>
      <th>#</th><th>Device</th><th>Boot Time</th><th>Revision</th><th>Source</th><th>When</th>
    </tr></thead>
    <tbody>
    {% for b in boots %}
      {% set dev_avg = avgs.get(b.get('device_id')) %}
      {% set color = '#9ece6a' if not dev_avg or b.boot_time_s < dev_avg * slow_mult
                     else '#e0af68' if b.boot_time_s < dev_avg * very_slow_mult
                     else '#f7768e' %}
      <tr style="cursor:pointer" onclick="window.location='{{ url_for('boot_detail', boot_id=b.id) }}'">
        <td style="color:#565f89">{{ b.id }}</td>
        <td>{{ b.device_name }}</td>
        <td style="color:{{ color }};font-weight:600">{{ "%.1f"|format(b.boot_time_s) }}s</td>
        <td><span class="badge badge-blue">{{ b.revision }}</span></td>
        <td style="color:#565f89;font-size:11px">{{ b.source }}</td>
        <td style="color:#565f89;font-size:11px">{{ b.collected_at }}</td>
      </tr>
    {% else %}
      <tr><td colspan="6" style="text-align:center;padding:24px;color:#565f89">No boots match filters</td></tr>
    {% endfor %}
    </tbody>
  </table>
</div>

{# Pagination #}
{% set total_pages = ((total - 1) // per_page + 1) if total > 0 else 1 %}
{% if total_pages > 1 %}
<div style="display:flex;gap:8px;justify-content:center;margin-top:16px">
  {% if page > 1 %}
    <a class="btn btn-secondary" href="?page={{ page-1 }}&device={{ device_f }}&revision={{ rev_f }}&date={{ date_f }}">← Prev</a>
  {% endif %}
  <span style="color:#565f89;align-self:center;font-size:13px">Page {{ page }} / {{ total_pages }}</span>
  {% if page < total_pages %}
    <a class="btn btn-secondary" href="?page={{ page+1 }}&device={{ device_f }}&revision={{ rev_f }}&date={{ date_f }}">Next →</a>
  {% endif %}
</div>
{% endif %}
{% endblock %}
```

- [ ] **Step 3: Run tests**

```bash
cd web && python -m pytest ../tests/test_routes.py::test_boots_200 -v
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add web/app.py web/templates/boots.html
git commit -m "feat: boots list page with filters and pagination"
```

---

### Task 10: Boot detail page

**Files:**
- Modify: `web/app.py` (boot_detail route)
- Modify: `web/templates/boot_detail.html`

- [ ] **Step 1: Update boot_detail route in app.py**

Replace stub `boot_detail()`:

```python
@app.route('/boot/<int:boot_id>')
def boot_detail(boot_id):
    boot = fetch_one(
        'SELECT b.*, d.name AS device_name, d.id AS device_id, r.revision '
        'FROM bw_boots b '
        'JOIN bw_devices d ON d.id=b.device_id '
        'JOIN bw_sw_revisions r ON r.id=b.revision_id '
        'WHERE b.id=%s', (boot_id,)
    )
    if not boot:
        abort(404)

    blame = fetch_all(
        'SELECT service, time_s FROM bw_blame_entries WHERE boot_id=%s ORDER BY time_s DESC',
        (boot_id,)
    )
    max_blame = blame[0]['time_s'] if blame else 1

    # Last 10 boots for this device (for trend chart)
    trend = fetch_all(
        'SELECT b.id, b.boot_time_s, b.collected_at '
        'FROM bw_boots b WHERE b.device_id=%s ORDER BY b.collected_at DESC LIMIT 10',
        (boot['device_id'],)
    )
    trend = list(reversed(trend))
    trend_max = max((t['boot_time_s'] for t in trend), default=1)

    dev_avg = (fetch_one(
        'SELECT AVG(boot_time_s) AS a FROM bw_boots WHERE device_id=%s',
        (boot['device_id'],)
    ) or {}).get('a', boot['boot_time_s'])

    delta = boot['boot_time_s'] - dev_avg

    slow_mult      = float(os.environ.get('SLOW_BOOT_MULTIPLIER', 1.2))
    very_slow_mult = float(os.environ.get('VERY_SLOW_BOOT_MULTIPLIER', 2.0))

    return render_template('boot_detail.html',
        boot=boot, blame=blame, max_blame=max_blame,
        trend=trend, trend_max=trend_max,
        dev_avg=dev_avg, delta=delta,
        slow_mult=slow_mult, very_slow_mult=very_slow_mult,
    )
```

- [ ] **Step 2: Update boot_detail.html**

```html
{% extends "base.html" %}
{% block title %}Boot #{{ boot.id }} — BootWatch{% endblock %}
{% block content %}

{# Header #}
<div class="page-header">
  <div style="display:flex;align-items:baseline;gap:16px;flex-wrap:wrap">
    <h1>{{ boot.device_name }} — Boot #{{ boot.id }}</h1>
    {% set color = '#9ece6a' if boot.boot_time_s < dev_avg * slow_mult
                   else '#e0af68' if boot.boot_time_s < dev_avg * very_slow_mult
                   else '#f7768e' %}
    <span style="font-size:28px;font-weight:700;color:{{ color }}">{{ "%.1f"|format(boot.boot_time_s) }}s</span>
    <span style="color:{{ '#9ece6a' if delta <= 0 else '#f7768e' }};font-size:14px">
      {{ "▲ +%.1f"|format(delta) if delta > 0 else "▼ %.1f"|format(delta) }}s vs avg
    </span>
  </div>
  <p>
    <span class="badge badge-blue">{{ boot.revision }}</span>
    &nbsp;{{ boot.collected_at }}
    &nbsp;<a href="{{ url_for('device_detail', device_id=boot.device_id) }}" style="color:#565f89;font-size:12px">← {{ boot.device_name }}</a>
  </p>
</div>

<div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">

  {# Blame table #}
  <div class="card" style="padding:0">
    <div style="padding:12px 16px"><h2>Service Blame</h2></div>
    <table>
      <thead><tr><th>Service</th><th>Time</th><th>Share</th></tr></thead>
      <tbody>
      {% for entry in blame %}
        {% set pct = ((entry.time_s / max_blame) * 100)|int %}
        {% set c = '#9ece6a' if entry.time_s < 1 else '#e0af68' if entry.time_s < 5 else '#f7768e' %}
        <tr>
          <td style="font-size:12px">{{ entry.service }}</td>
          <td style="color:{{ c }};font-weight:600;white-space:nowrap">{{ "%.3f"|format(entry.time_s) }}s</td>
          <td style="width:120px">
            <div class="bar-wrap">
              <div class="bar-fill" style="width:{{ pct }}%;background:{{ c }}"></div>
            </div>
          </td>
        </tr>
      {% else %}
        <tr><td colspan="3" style="text-align:center;padding:20px;color:#565f89">No blame data</td></tr>
      {% endfor %}
      </tbody>
    </table>
  </div>

  {# Right column: trend + critical chain #}
  <div>
    {# Boot time trend bar chart #}
    <div class="card">
      <h2>Boot Time Trend — last {{ trend|length }} boots</h2>
      <div style="display:flex;align-items:flex-end;gap:4px;height:60px">
      {% for t in trend %}
        {% set pct = ((t.boot_time_s / trend_max) * 100)|int %}
        {% set c = '#9ece6a' if t.boot_time_s < dev_avg * slow_mult
                   else '#e0af68' if t.boot_time_s < dev_avg * very_slow_mult
                   else '#f7768e' %}
        <div style="flex:1;background:{{ c }};border-radius:2px 2px 0 0;height:{{ pct }}%;
                    {{ 'outline:2px solid #ffffff44;' if t.id == boot.id else '' }}"
             title="{{ '%.1f'|format(t.boot_time_s) }}s · {{ t.collected_at }}"></div>
      {% endfor %}
      </div>
      <div style="display:flex;justify-content:space-between;margin-top:4px;font-size:9px;color:#565f89">
        <span>oldest</span><span>newest</span>
      </div>
    </div>

    {# Critical chain #}
    <div class="card">
      <h2>Critical Chain</h2>
      {% if boot.raw_chain %}
        <pre style="font-size:11px;color:#c0caf5;overflow-x:auto;white-space:pre-wrap;
                    background:#1a1b26;padding:10px;border-radius:4px;line-height:1.5">{{ boot.raw_chain }}</pre>
      {% else %}
        <p style="color:#565f89;font-size:13px">No critical chain data collected</p>
      {% endif %}
    </div>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 3: Run tests**

```bash
cd web && python -m pytest ../tests/test_routes.py::test_boot_detail_404 -v
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add web/app.py web/templates/boot_detail.html
git commit -m "feat: boot detail page — blame table, trend chart, critical chain"
```

---

### Task 11: Devices page + device detail

**Files:**
- Modify: `web/app.py` (devices + device_detail routes)
- Modify: `web/templates/devices.html`
- Modify: `web/templates/device_detail.html`

- [ ] **Step 1: Update devices route in app.py**

Replace stub `devices()`:

```python
@app.route('/devices')
def devices():
    rows = fetch_all('''
        SELECT d.id, d.name, d.label, d.ip_addr, d.created_at,
               COUNT(b.id) AS boot_count,
               AVG(b.boot_time_s) AS avg_boot,
               MIN(b.boot_time_s) AS min_boot,
               MAX(b.boot_time_s) AS max_boot,
               MAX(b.collected_at) AS last_seen
        FROM bw_devices d
        LEFT JOIN bw_boots b ON b.device_id = d.id
        GROUP BY d.id
        ORDER BY d.name
    ''')
    return render_template('devices.html', devices=rows)
```

Replace stub `device_detail()`:

```python
@app.route('/device/<int:device_id>')
def device_detail(device_id):
    device = fetch_one('SELECT * FROM bw_devices WHERE id=%s', (device_id,))
    if not device:
        abort(404)
    boots_list = fetch_all(
        'SELECT b.id, b.boot_time_s, b.collected_at, b.source, r.revision '
        'FROM bw_boots b JOIN bw_sw_revisions r ON r.id=b.revision_id '
        'WHERE b.device_id=%s ORDER BY b.collected_at DESC LIMIT 50',
        (device_id,)
    )
    stats = fetch_one(
        'SELECT COUNT(*) AS n, AVG(boot_time_s) AS avg_t, MIN(boot_time_s) AS min_t, MAX(boot_time_s) AS max_t '
        'FROM bw_boots WHERE device_id=%s', (device_id,)
    ) or {}
    slow_mult      = float(os.environ.get('SLOW_BOOT_MULTIPLIER', 1.2))
    very_slow_mult = float(os.environ.get('VERY_SLOW_BOOT_MULTIPLIER', 2.0))
    return render_template('device_detail.html',
        device=device, boots=boots_list, stats=stats,
        slow_mult=slow_mult, very_slow_mult=very_slow_mult,
    )
```

- [ ] **Step 2: Update devices.html**

```html
{% extends "base.html" %}
{% block title %}Devices — BootWatch{% endblock %}
{% block content %}
<div class="page-header"><h1>Devices</h1><p>{{ devices|length }} device(s) registered</p></div>
<div class="card" style="padding:0">
  <table>
    <thead><tr>
      <th>Name</th><th>Label</th><th>IP</th><th>Boots</th>
      <th>Avg Boot</th><th>Min</th><th>Max</th><th>Last Seen</th>
    </tr></thead>
    <tbody>
    {% for d in devices %}
      <tr style="cursor:pointer" onclick="window.location='{{ url_for('device_detail', device_id=d.id) }}'">
        <td><a href="{{ url_for('device_detail', device_id=d.id) }}">{{ d.name }}</a></td>
        <td style="color:#565f89;font-size:12px">{{ d.label or '—' }}</td>
        <td style="font-family:monospace;font-size:12px;color:#565f89">{{ d.ip_addr }}</td>
        <td>{{ d.boot_count }}</td>
        <td>{{ "%.1f"|format(d.avg_boot) if d.avg_boot else "—" }}s</td>
        <td style="color:#9ece6a">{{ "%.1f"|format(d.min_boot) if d.min_boot else "—" }}s</td>
        <td style="color:#f7768e">{{ "%.1f"|format(d.max_boot) if d.max_boot else "—" }}s</td>
        <td style="color:#565f89;font-size:11px">{{ d.last_seen or "—" }}</td>
      </tr>
    {% else %}
      <tr><td colspan="8" style="text-align:center;padding:24px;color:#565f89">No devices yet</td></tr>
    {% endfor %}
    </tbody>
  </table>
</div>
{% endblock %}
```

- [ ] **Step 3: Update device_detail.html**

```html
{% extends "base.html" %}
{% block title %}{{ device.name }} — BootWatch{% endblock %}
{% block content %}
<div class="page-header">
  <h1>{{ device.name }}</h1>
  <p style="font-family:monospace">{{ device.ip_addr }}{% if device.label %} · {{ device.label }}{% endif %}</p>
</div>

<div class="card-grid" style="grid-template-columns:repeat(4,1fr)">
  <div class="stat-card" style="--accent-bar:#7aa2f7">
    <div class="number">{{ stats.n or 0 }}</div><div class="label">Total Boots</div>
  </div>
  <div class="stat-card" style="--accent-bar:#9ece6a">
    <div class="number">{{ "%.1f"|format(stats.avg_t) if stats.avg_t else "—" }}s</div>
    <div class="label">Avg Boot</div>
  </div>
  <div class="stat-card" style="--accent-bar:#9ece6a">
    <div class="number">{{ "%.1f"|format(stats.min_t) if stats.min_t else "—" }}s</div>
    <div class="label">Best Boot</div>
  </div>
  <div class="stat-card" style="--accent-bar:#f7768e">
    <div class="number">{{ "%.1f"|format(stats.max_t) if stats.max_t else "—" }}s</div>
    <div class="label">Worst Boot</div>
  </div>
</div>

<div class="card" style="padding:0">
  <div style="padding:12px 16px"><h2>Boot History (last 50)</h2></div>
  <table>
    <thead><tr><th>#</th><th>Boot Time</th><th>Revision</th><th>Source</th><th>When</th></tr></thead>
    <tbody>
    {% for b in boots %}
      {% set c = '#9ece6a' if stats.avg_t and b.boot_time_s < stats.avg_t * slow_mult
                 else '#e0af68' if stats.avg_t and b.boot_time_s < stats.avg_t * very_slow_mult
                 else '#f7768e' if stats.avg_t else '#c0caf5' %}
      <tr style="cursor:pointer" onclick="window.location='{{ url_for('boot_detail', boot_id=b.id) }}'">
        <td style="color:#565f89">{{ b.id }}</td>
        <td style="color:{{ c }};font-weight:600">{{ "%.1f"|format(b.boot_time_s) }}s</td>
        <td><span class="badge badge-blue">{{ b.revision }}</span></td>
        <td style="color:#565f89;font-size:11px">{{ b.source }}</td>
        <td style="color:#565f89;font-size:11px">{{ b.collected_at }}</td>
      </tr>
    {% else %}
      <tr><td colspan="5" style="text-align:center;padding:24px;color:#565f89">No boots for this device</td></tr>
    {% endfor %}
    </tbody>
  </table>
</div>
{% endblock %}
```

- [ ] **Step 4: Run tests**

```bash
cd web && python -m pytest ../tests/test_routes.py -k "devices" -v
```

Expected: PASS (test_devices_200, test_device_detail_404)

- [ ] **Step 5: Commit**

```bash
git add web/app.py web/templates/devices.html web/templates/device_detail.html
git commit -m "feat: devices list and device detail pages"
```

---

### Task 12: Firmware page

**Files:**
- Modify: `web/app.py` (firmware route)
- Modify: `web/templates/firmware.html`

- [ ] **Step 1: Update firmware route in app.py**

Replace stub `firmware()`:

```python
@app.route('/firmware')
def firmware():
    revisions = fetch_all('''
        SELECT r.id, r.revision,
               COUNT(DISTINCT b.device_id) AS device_count,
               COUNT(b.id)                 AS boot_count,
               AVG(b.boot_time_s)          AS avg_boot,
               MIN(b.boot_time_s)          AS min_boot,
               MAX(b.boot_time_s)          AS max_boot
        FROM bw_sw_revisions r
        LEFT JOIN bw_boots b ON b.revision_id = r.id
        GROUP BY r.id
        ORDER BY r.revision DESC
    ''')
    return render_template('firmware.html', revisions=revisions)
```

- [ ] **Step 2: Update firmware.html**

```html
{% extends "base.html" %}
{% block title %}Firmware — BootWatch{% endblock %}
{% block content %}
<div class="page-header"><h1>Firmware Revisions</h1><p>Boot time per SW revision</p></div>
<div class="card" style="padding:0">
  <table>
    <thead><tr>
      <th>Revision</th><th>Devices</th><th>Boots</th>
      <th>Avg Boot</th><th>Min</th><th>Max</th>
    </tr></thead>
    <tbody>
    {% for r in revisions %}
      <tr style="cursor:pointer"
          onclick="window.location='{{ url_for('boots') }}?revision={{ r.revision }}'">
        <td><span class="badge badge-blue">{{ r.revision }}</span></td>
        <td>{{ r.device_count }}</td>
        <td>{{ r.boot_count }}</td>
        <td style="font-weight:600">{{ "%.1f"|format(r.avg_boot) if r.avg_boot else "—" }}s</td>
        <td style="color:#9ece6a">{{ "%.1f"|format(r.min_boot) if r.min_boot else "—" }}s</td>
        <td style="color:#f7768e">{{ "%.1f"|format(r.max_boot) if r.max_boot else "—" }}s</td>
      </tr>
    {% else %}
      <tr><td colspan="6" style="text-align:center;padding:24px;color:#565f89">No revisions yet</td></tr>
    {% endfor %}
    </tbody>
  </table>
</div>
{% endblock %}
```

- [ ] **Step 3: Run tests**

```bash
cd web && python -m pytest ../tests/test_routes.py::test_firmware_200 -v
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add web/app.py web/templates/firmware.html
git commit -m "feat: firmware page — per-revision boot stats"
```

---

### Task 13: Services page

**Files:**
- Modify: `web/app.py` (services route)
- Modify: `web/templates/services.html`

- [ ] **Step 1: Update services route in app.py**

Replace stub `services()`:

```python
@app.route('/services')
def services():
    rev_f = request.args.get('revision', '')

    where = ''
    args = []
    if rev_f:
        where = 'JOIN bw_boots bt ON bt.id=be.boot_id JOIN bw_sw_revisions r ON r.id=bt.revision_id WHERE r.revision=%s'
        args = [rev_f]

    rows = fetch_all(
        f'''SELECT be.service,
               AVG(be.time_s)  AS avg_time,
               MAX(be.time_s)  AS max_time,
               COUNT(*)        AS n_boots,
               d.name          AS worst_device
        FROM bw_blame_entries be
        JOIN bw_boots bt2 ON bt2.id = (
            SELECT boot_id FROM bw_blame_entries be2
            WHERE be2.service = be.service ORDER BY be2.time_s DESC LIMIT 1
        )
        JOIN bw_devices d ON d.id = bt2.device_id
        {where}
        GROUP BY be.service
        ORDER BY avg_time DESC LIMIT 50''',
        args
    )

    all_revisions = fetch_all('SELECT revision FROM bw_sw_revisions ORDER BY revision DESC')
    max_time = rows[0]['avg_time'] if rows else 1

    return render_template('services.html',
        services=rows, max_time=max_time,
        all_revisions=all_revisions, rev_f=rev_f,
    )
```

- [ ] **Step 2: Update services.html**

```html
{% extends "base.html" %}
{% block title %}Services — BootWatch{% endblock %}
{% block content %}
<div class="page-header"><h1>Services</h1><p>Fleet-wide systemd service boot times</p></div>

<form method="get" class="filters">
  <div class="filter-group">
    <label>Revision</label>
    <select name="revision" onchange="this.form.submit()">
      <option value="">All revisions</option>
      {% for r in all_revisions %}
        <option value="{{ r.revision }}" {{ 'selected' if rev_f == r.revision }}>{{ r.revision }}</option>
      {% endfor %}
    </select>
  </div>
</form>

<div class="card" style="padding:0">
  <table>
    <thead><tr>
      <th>Service</th><th>Fleet Avg</th><th>Worst Time</th><th>Worst Device</th><th>Boots</th><th>Trend</th>
    </tr></thead>
    <tbody>
    {% for svc in services %}
      <tr>
        <td style="font-size:12px">{{ svc.service }}</td>
        <td style="font-weight:600;color:#e0af68">{{ "%.3f"|format(svc.avg_time) }}s</td>
        <td style="color:#f7768e">{{ "%.3f"|format(svc.max_time) }}s</td>
        <td style="color:#565f89;font-size:12px">{{ svc.worst_device or "—" }}</td>
        <td style="color:#565f89">{{ svc.n_boots }}</td>
        <td style="width:100px">
          <div class="bar-wrap">
            <div class="bar-fill" style="width:{{ ((svc.avg_time/max_time)*100)|int }}%;background:#e0af68"></div>
          </div>
        </td>
      </tr>
    {% else %}
      <tr><td colspan="6" style="text-align:center;padding:24px;color:#565f89">No service data yet</td></tr>
    {% endfor %}
    </tbody>
  </table>
</div>
{% endblock %}
```

- [ ] **Step 3: Run tests**

```bash
cd web && python -m pytest ../tests/test_routes.py::test_services_200 -v
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add web/app.py web/templates/services.html
git commit -m "feat: services page — fleet-wide service blame ranking"
```

---

### Task 14: Perf page

**Files:**
- Modify: `web/app.py` (perf route + flamegraph serve route)
- Modify: `web/templates/perf.html`

- [ ] **Step 1: Update perf route in app.py**

Replace stub `perf()`:

```python
@app.route('/perf')
def perf():
    device_f  = request.args.get('device', '')
    rev_f     = request.args.get('revision', '')

    where_parts = []
    args = []
    if device_f:
        where_parts.append('d.name = %s')
        args.append(device_f)
    if rev_f:
        where_parts.append('r.revision = %s')
        args.append(rev_f)
    where = ('WHERE ' + ' AND '.join(where_parts)) if where_parts else ''

    stats = fetch_all(
        f'SELECT ps.*, d.name AS device_name, r.revision '
        f'FROM bw_perf_stats ps '
        f'JOIN bw_devices d ON d.id=ps.device_id '
        f'JOIN bw_sw_revisions r ON r.id=ps.revision_id '
        f'{where} ORDER BY ps.collected_at DESC LIMIT 20',
        args
    )

    # Latest flamegraph for selected device (or any device)
    fg_where = 'WHERE d.name=%s' if device_f else ''
    fg_args  = [device_f] if device_f else []
    flamegraph = fetch_one(
        f'SELECT fg.*, d.name AS device_name, r.revision '
        f'FROM bw_flamegraphs fg '
        f'JOIN bw_devices d ON d.id=fg.device_id '
        f'JOIN bw_sw_revisions r ON r.id=fg.revision_id '
        f'{fg_where} ORDER BY fg.generated_at DESC LIMIT 1',
        fg_args
    )

    # IPC trend data for chart (all snapshots for device filter)
    ipc_trend = fetch_all(
        f'SELECT ps.ipc, ps.collected_at, r.revision '
        f'FROM bw_perf_stats ps '
        f'JOIN bw_sw_revisions r ON r.id=ps.revision_id '
        f'{"JOIN bw_devices d ON d.id=ps.device_id WHERE d.name=%s" if device_f else ""} '
        f'ORDER BY ps.collected_at ASC LIMIT 20',
        [device_f] if device_f else []
    )

    all_devices   = fetch_all('SELECT DISTINCT name FROM bw_devices ORDER BY name')
    all_revisions = fetch_all('SELECT revision FROM bw_sw_revisions ORDER BY revision DESC')

    # Selected device id for Profile Now button
    selected_device = fetch_one('SELECT id FROM bw_devices WHERE name=%s', (device_f,)) if device_f else None

    return render_template('perf.html',
        stats=stats, flamegraph=flamegraph, ipc_trend=ipc_trend,
        all_devices=all_devices, all_revisions=all_revisions,
        device_f=device_f, rev_f=rev_f,
        selected_device=selected_device,
    )
```

Add flamegraph SVG serve route (add inside `create_app()`):

```python
@app.route('/flamegraph/<int:fg_id>/svg')
def serve_flamegraph_svg(fg_id):
    import os
    from flask import send_file, abort
    fg = fetch_one('SELECT svg_path FROM bw_flamegraphs WHERE id=%s AND status=%s', (fg_id, 'done'))
    if not fg or not fg['svg_path'] or not os.path.exists(fg['svg_path']):
        abort(404)
    return send_file(fg['svg_path'], mimetype='image/svg+xml')
```

- [ ] **Step 2: Update perf.html**

```html
{% extends "base.html" %}
{% block title %}Perf — BootWatch{% endblock %}
{% block content %}
<div class="page-header"><h1>Perf</h1><p>CPU counters and flamegraph profiling</p></div>

<form method="get" class="filters">
  <div class="filter-group">
    <label>Device</label>
    <select name="device" onchange="this.form.submit()">
      <option value="">All devices</option>
      {% for d in all_devices %}
        <option value="{{ d.name }}" {{ 'selected' if device_f == d.name }}>{{ d.name }}</option>
      {% endfor %}
    </select>
  </div>
  <div class="filter-group">
    <label>Revision</label>
    <select name="revision" onchange="this.form.submit()">
      <option value="">All revisions</option>
      {% for r in all_revisions %}
        <option value="{{ r.revision }}" {{ 'selected' if rev_f == r.revision }}>{{ r.revision }}</option>
      {% endfor %}
    </select>
  </div>
  {% if selected_device %}
  <div style="margin-left:auto;align-self:flex-end">
    <button type="button" class="btn btn-primary"
            onclick="triggerFlamegraph({{ selected_device.id }}, '{{ rev_f or 'unknown' }}')">
      ⚡ Profile Now
    </button>
    <span id="fg-status" style="font-size:11px;color:#565f89;margin-left:8px"></span>
  </div>
  {% endif %}
</form>

{# Latest perf stat snapshot #}
{% if stats %}
{% set s = stats[0] %}
<div class="card">
  <h2>Latest CPU Counters — {{ s.device_name }} · {{ s.revision }} · {{ s.collected_at }}</h2>
  <div class="card-grid" style="grid-template-columns:repeat(4,1fr)">
    <div class="stat-card" style="--accent-bar:#7aa2f7">
      <div class="number" style="font-size:28px">{{ "%.2f"|format(s.ipc) if s.ipc else "—" }}</div>
      <div class="label">IPC</div>
    </div>
    <div class="stat-card" style="--accent-bar:#f7768e">
      <div class="number" style="font-size:28px">{{ "%.1f"|format(s.cache_miss_pct) if s.cache_miss_pct else "—" }}%</div>
      <div class="label">Cache Miss</div>
    </div>
    <div class="stat-card" style="--accent-bar:#e0af68">
      <div class="number" style="font-size:28px">{{ "%.1f"|format(s.branch_miss_pct) if s.branch_miss_pct else "—" }}%</div>
      <div class="label">Branch Miss</div>
    </div>
    <div class="stat-card" style="--accent-bar:#9ece6a">
      <div class="number" style="font-size:28px">{{ "%.0fB"|format(s.cycles/1e9) if s.cycles else "—" }}</div>
      <div class="label">Cycles ({{ s.duration_s }}s)</div>
    </div>
  </div>

  {# IPC trend bar chart #}
  {% if ipc_trend %}
  <div style="margin-top:12px">
    <div style="font-size:10px;color:#565f89;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px">IPC trend</div>
    {% set max_ipc = ipc_trend | map(attribute='ipc') | select | list | max %}
    <div style="display:flex;align-items:flex-end;gap:4px;height:48px">
    {% for t in ipc_trend %}
      {% if t.ipc %}
      <div style="flex:1;background:#7aa2f7;border-radius:2px 2px 0 0;opacity:0.8;
                  height:{{ ((t.ipc / max_ipc) * 100)|int }}%"
           title="{{ '%.2f'|format(t.ipc) }} IPC · {{ t.revision }} · {{ t.collected_at }}"></div>
      {% endif %}
    {% endfor %}
    </div>
  </div>
  {% endif %}
</div>
{% else %}
<div class="card"><p style="color:#565f89">No perf stat data yet. Run collect.py to collect counters.</p></div>
{% endif %}

{# Flamegraph section #}
<div class="card">
  <h2>Flamegraph{% if flamegraph %} — {{ flamegraph.device_name }} · {{ flamegraph.revision }}{% endif %}</h2>

  {% if flamegraph and flamegraph.status == 'done' and flamegraph.svg_path %}
    <div style="font-size:11px;color:#565f89;margin-bottom:8px">
      Generated {{ flamegraph.generated_at }} · {{ flamegraph.revision }}
    </div>
    <div style="background:#1a1b26;border-radius:4px;overflow:hidden;border:1px solid #414868">
      <object data="/flamegraph/{{ flamegraph.id }}/svg" type="image/svg+xml"
              style="width:100%;height:300px;display:block">
        <p style="color:#565f89;padding:20px">SVG not available</p>
      </object>
    </div>
    <div style="display:flex;gap:8px;margin-top:8px">
      <a href="/flamegraph/{{ flamegraph.id }}/svg" download class="btn btn-secondary">⬇ Download SVG</a>
    </div>
  {% elif flamegraph and flamegraph.status in ('pending', 'running') %}
    <p style="color:#e0af68">⏳ Flamegraph generation in progress...</p>
  {% elif flamegraph and flamegraph.status == 'failed' %}
    <p style="color:#f7768e">Flamegraph generation failed. Check device SSH access.</p>
  {% else %}
    <p style="color:#565f89">No flamegraph yet.
      {% if selected_device %}Click "Profile Now" above to generate one.
      {% else %}Select a device to generate a flamegraph.{% endif %}
    </p>
  {% endif %}
</div>
{% endblock %}

{% block scripts %}
<script>
function triggerFlamegraph(deviceId, revision) {
  var statusEl = document.getElementById('fg-status');
  statusEl.textContent = 'Triggering...';
  fetch('/api/flamegraph/' + deviceId, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({revision: revision})
  }).then(function(r) { return r.json(); }).then(function(data) {
    if (data.flamegraph_id) {
      statusEl.textContent = 'Profiling (~15s)...';
      pollFlamegraph(deviceId, data.flamegraph_id, statusEl);
    } else {
      statusEl.textContent = 'Error: ' + (data.error || 'unknown');
    }
  }).catch(function(e) {
    statusEl.textContent = 'Request failed';
  });
}

function pollFlamegraph(deviceId, fgId, statusEl) {
  var interval = setInterval(function() {
    fetch('/api/flamegraph/' + deviceId + '/status')
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.status === 'done') {
          clearInterval(interval);
          statusEl.textContent = 'Done! Reloading...';
          setTimeout(function() { window.location.reload(); }, 800);
        } else if (data.status === 'failed') {
          clearInterval(interval);
          statusEl.textContent = 'Failed — check SSH access';
        } else {
          statusEl.textContent = 'Running (' + data.status + ')...';
        }
      });
  }, 2000);
}
</script>
{% endblock %}
```

- [ ] **Step 3: Run tests**

```bash
cd web && python -m pytest ../tests/test_routes.py::test_perf_200 -v
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add web/app.py web/templates/perf.html
git commit -m "feat: perf page — stat cards, IPC trend, flamegraph UI with polling"
```

---

### Task 15: collect.py — single-device SSH collector

**Files:**
- Create: `tools/collect.py`

- [ ] **Step 1: Create collect.py**

```python
#!/usr/bin/env python3
# tools/collect.py — SSH into one device, collect boot + perf data, POST to BootWatch server
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
    Line looks like: Startup finished in 1.2s (kernel) + 43.9s (userspace) = 45.2s
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
    """Parse `perf stat` output for key counters.
    Returns dict with cycles, instructions, ipc, cache_misses, etc."""
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

    cycles       = int(cycles_s)       if cycles_s       else None
    instructions = int(instructions_s) if instructions_s else None
    ipc          = float(ipc_s)        if ipc_s          else None
    cache_misses = int(cmiss_s)        if cmiss_s        else None
    cache_refs   = int(cref_s)         if cref_s         else None
    branch_misses = int(bmiss_s)       if bmiss_s        else None
    branch_total  = int(btot_s)        if btot_s         else None

    cache_miss_pct  = (cache_misses / cache_refs * 100)   if cache_misses and cache_refs else None
    branch_miss_pct = (branch_misses / branch_total * 100) if branch_misses and branch_total else None

    return {
        'duration_s':     duration_s,
        'cycles':         cycles,
        'instructions':   instructions,
        'ipc':            ipc,
        'cache_misses':   cache_misses,
        'cache_refs':     cache_refs,
        'cache_miss_pct': cache_miss_pct,
        'branch_misses':  branch_misses,
        'branch_total':   branch_total,
        'branch_miss_pct': branch_miss_pct,
        'raw_output':     output,
    }


def detect_revision(client):
    out, _, _ = ssh_run(client, 'grep ^VERSION_ID= /etc/os-release || echo VERSION_ID=unknown')
    m = re.search(r'VERSION_ID="?([^"\n]+)"?', out)
    return m.group(1) if m else 'unknown'


def main():
    parser = argparse.ArgumentParser(description='BootWatch single-device collector')
    parser.add_argument('--device',       required=True,         help='Device IP address')
    parser.add_argument('--server',       default='127.0.0.1',   help='BootWatch server IP')
    parser.add_argument('--port',         default=8080, type=int, help='BootWatch server port')
    parser.add_argument('--ssh-user',     default='root',        help='SSH username')
    parser.add_argument('--ssh-port',     default=22, type=int,  help='SSH port')
    parser.add_argument('--ssh-key',      default=None,          help='Path to SSH private key')
    parser.add_argument('--name',         default='device',      help='Device name')
    parser.add_argument('--label',        default='',            help='Device label')
    parser.add_argument('--version',      default=None,          help='SW revision (auto-detect if omitted)')
    parser.add_argument('--skip-perf',    action='store_true',   help='Skip perf stat collection')
    parser.add_argument('--perf-duration',default=10, type=int,  help='perf stat window (seconds)')
    args = parser.parse_args()

    print(f'[*] Connecting to {args.device}:{args.ssh_port} as {args.ssh_user}')
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    connect_kwargs = dict(
        hostname=args.device,
        username=args.ssh_user,
        port=args.ssh_port,
        timeout=30,
    )
    if args.ssh_key:
        connect_kwargs['key_filename'] = args.ssh_key
    client.connect(**connect_kwargs)

    # SW revision
    revision = args.version or detect_revision(client)
    print(f'[*] Revision: {revision}')

    # systemd-analyze
    print('[*] Running systemd-analyze...')
    out, _, _ = ssh_run(client, 'systemd-analyze')
    boot_time = parse_analyze(out)
    if boot_time is None:
        print('[!] Could not parse boot time from systemd-analyze output', file=sys.stderr)
        print(out)
        sys.exit(1)
    print(f'[*] Boot time: {boot_time:.1f}s')

    # systemd-analyze blame
    print('[*] Running systemd-analyze blame...')
    blame_out, _, _ = ssh_run(client, 'systemd-analyze blame')
    blame = parse_blame(blame_out)
    print(f'[*] {len(blame)} blame entries')

    # systemd-analyze critical-chain
    print('[*] Running systemd-analyze critical-chain...')
    chain_out, _, _ = ssh_run(client, 'systemd-analyze critical-chain')

    # perf stat
    perf_stat = None
    if not args.skip_perf:
        print(f'[*] Running perf stat (duration={args.perf_duration}s)...')
        perf_out, perf_err, perf_rc = ssh_run(
            client,
            f'perf stat -a sleep {args.perf_duration} 2>&1',
            timeout=args.perf_duration + 30
        )
        if perf_rc == 0 or perf_out or perf_err:
            combined = perf_out + perf_err
            perf_stat = parse_perf_stat(combined, args.perf_duration)
            print(f'[*] perf IPC: {perf_stat["ipc"]}')
        else:
            print('[!] perf stat failed — skipping', file=sys.stderr)

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
```

- [ ] **Step 2: Smoke test parse functions**

```bash
python3 -c "
import sys; sys.path.insert(0, 'tools')
from collect import parse_blame, parse_analyze, parse_perf_stat

analyze_out = 'Startup finished in 1.2s (kernel) + 43.9s (userspace) = 45.1s'
assert parse_analyze(analyze_out) == 45.1

blame_out = '''  18.450s NetworkManager.service
   6.100s docker.service'''
blame = parse_blame(blame_out)
assert blame[0] == {'service': 'NetworkManager.service', 'time_s': 18.45}
assert blame[1] == {'service': 'docker.service', 'time_s': 6.1}
print('parse tests PASS')
"
```

Expected: `parse tests PASS`

- [ ] **Step 3: Commit**

```bash
git add tools/collect.py
git commit -m "feat: collect.py — single-device SSH boot+perf collector"
```

---

### Task 16: collect-all.py + install-hook.py

**Files:**
- Create: `tools/collect-all.py`
- Create: `tools/install-hook.py`

- [ ] **Step 1: Create collect-all.py**

```python
#!/usr/bin/env python3
# tools/collect-all.py — run collect.py in parallel across multiple devices
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
        print(f'{prefix} {line}')
    return name, result.returncode


def main():
    parser = argparse.ArgumentParser(description='BootWatch multi-device collector')
    parser.add_argument('--devices-file', default='tools/devices.txt', help='Path to devices list file')
    parser.add_argument('--devices',      nargs='+', help='Device IPs directly (overrides --devices-file)')
    parser.add_argument('--server',       default='127.0.0.1')
    parser.add_argument('--port',         default=8080, type=int)
    parser.add_argument('--ssh-user',     default='root')
    parser.add_argument('--ssh-port',     default=22, type=int)
    parser.add_argument('--ssh-key',      default=None)
    parser.add_argument('--version',      default=None)
    parser.add_argument('--skip-perf',    action='store_true')
    parser.add_argument('--perf-duration',default=10, type=int)
    parser.add_argument('--threads',      default=4, type=int)
    args = parser.parse_args()

    common = ['--server', args.server, '--port', str(args.port),
              '--ssh-user', args.ssh_user, '--ssh-port', str(args.ssh_port)]
    if args.ssh_key:
        common += ['--ssh-key', args.ssh_key]
    if args.version:
        common += ['--version', args.version]
    if args.skip_perf:
        common.append('--skip-perf')
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
```

- [ ] **Step 2: Create install-hook.py**

```python
#!/usr/bin/env python3
# tools/install-hook.py — install boot-time reporting service on a device
import argparse
import sys
import paramiko


REPORT_SCRIPT = """\
#!/bin/sh
# BootWatch boot-time reporter — installed by install-hook.py
SERVER="{server}"
PORT="{port}"
VERSION_KEY="{version_key}"

BOOT_TIME=$(systemd-analyze 2>/dev/null | grep -oP '= \\K[\\d.]+(?=s)')
REVISION=$(grep "^${{VERSION_KEY}}=" /etc/os-release 2>/dev/null | cut -d= -f2 | tr -d '"')
REVISION=${{REVISION:-unknown}}
DEVICE_IP=$(hostname -I | awk '{{print $1}}')
DEVICE_NAME=$(hostname)

BLAME=$(systemd-analyze blame 2>/dev/null)
CHAIN=$(systemd-analyze critical-chain 2>/dev/null)
PERF_OUT=$(perf stat -a sleep 10 2>&1 || true)

PAYLOAD=$(printf '{{
  "device_ip": "%s",
  "device_name": "%s",
  "device_label": "",
  "revision": "%s",
  "source": "boot_hook",
  "boot_time_s": %s,
  "blame": [],
  "critical_chain": "%s"
}}' "$DEVICE_IP" "$DEVICE_NAME" "$REVISION" "$BOOT_TIME" "$(echo "$CHAIN" | head -20 | tr '"' "'")")

curl -sf -X POST -H "Content-Type: application/json" \\
     -d "$PAYLOAD" "http://$SERVER:$PORT/api/boot" || true
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
    parser.add_argument('--ssh-port',    default=22, type=int)
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

    # Write report script
    with sftp.open('/usr/local/bin/bootwatch-report.sh', 'w') as f:
        f.write(script)
    ssh_run(client, 'chmod +x /usr/local/bin/bootwatch-report.sh')
    print('[*] Installed /usr/local/bin/bootwatch-report.sh')

    # Write systemd unit
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
```

- [ ] **Step 3: Commit**

```bash
git add tools/collect-all.py tools/install-hook.py
git commit -m "feat: collect-all.py multi-device collector + install-hook.py boot hook installer"
```

---

### Task 17: Full integration test + README

**Files:**
- Create: `README.md`

- [ ] **Step 1: Run full test suite**

```bash
# Start test DB
docker compose -f docker-compose.yml -f docker-compose-local.yml up -d mariadb

# Run all tests
cd web && python -m pytest ../tests/ -v
```

Expected: All tests PASS. Fix any failures before proceeding.

- [ ] **Step 2: Smoke test with Docker**

```bash
cd /path/to/bootwatch
cp .env.example .env
docker compose -f docker-compose.yml -f docker-compose-local.yml up -d
# Wait ~15s for MariaDB healthcheck
docker compose logs flask-web
```

Open `http://localhost:8080` — verify Overview page loads with empty state ("No devices yet").

- [ ] **Step 3: Manual collect test**

```bash
# With a real device at 192.168.1.100:
python3 tools/collect.py \
    --device 192.168.1.100 \
    --name test-device \
    --server 127.0.0.1 \
    --port 8080

# Then reload http://localhost:8080 — device card should appear
```

- [ ] **Step 4: Create README.md**

```markdown
# BootWatch

Self-hosted boot analysis UI for embedded Linux devices. Tracks `systemd-analyze` blame, critical chain, and `perf` counters per boot — visualized across devices and firmware revisions.

## Quick Start (local)

```bash
cp .env.example .env
docker compose -f docker-compose.yml -f docker-compose-local.yml up -d
# UI at http://localhost:8080
```

## Collect from a device

```bash
pip install paramiko
python3 tools/collect.py --device 192.168.1.100 --name my-device --server 127.0.0.1 --port 8080
```

## Collect from all devices

```bash
cp tools/devices.txt.example tools/devices.txt
# Edit devices.txt — one device per line: IP name label
python3 tools/collect-all.py --devices-file tools/devices.txt --server 127.0.0.1
```

## Install boot hook (report on every boot)

```bash
python3 tools/install-hook.py --device 192.168.1.100 --server 10.0.0.5 --port 8080
```

## Pages

| Page | URL | Description |
|------|-----|-------------|
| Overview | `/` | Device grid, recent boots, slowest services |
| Boots | `/boots` | Paginated boot list, filterable |
| Boot detail | `/boot/<id>` | Blame table, trend chart, critical chain |
| Devices | `/devices` | All devices with stats |
| Firmware | `/firmware` | Per-revision boot time comparison |
| Services | `/services` | Fleet-wide service timing |
| Perf | `/perf` | CPU counters + on-demand flamegraph |

## Production deployment (with Traefik + TLS)

```bash
# Edit .env: set DOMAIN, ACME_EMAIL
docker compose -f docker-compose.yml -f docker-compose-production.yml up -d
```
```

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: README with quick start and page reference"
```


---

## Self-Review Notes (fixes applied inline)

### Fix 1: Flask app context in background thread (Task 7 + Task 5)

`collector.py`'s background thread calls `execute()` from `db.py`, which uses Flask's `g` — bound to the request context. The thread has no request context, so this would crash.

**Fix: pass `flask_app` to `start_flamegraph_job` and use `app.app_context()`.**

Updated Task 7 — replace `start_flamegraph_job` signature and body:

```python
def start_flamegraph_job(fg_id, device, revision_str, flask_app, duration_s=15):
    """Runs in a background thread. Pushes Flask app context for DB access."""
    with flask_app.app_context():
        execute('UPDATE bw_flamegraphs SET status=%s WHERE id=%s', ('running', fg_id))
        try:
            ssh = _ssh_connect(device)
            remote_perf = f'/tmp/bw-perf-{fg_id}.data'
            cmd = f'perf record -ag -o {remote_perf} sleep {duration_s}'
            stdin, stdout, stderr = ssh.exec_command(cmd, timeout=duration_s + 30)
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
                p1 = subprocess.Popen(['perf', 'script', '-i', local_perf], stdout=subprocess.PIPE)
                p2 = subprocess.Popen(['perl', STACKCOLLAPSE_BIN], stdin=p1.stdout, stdout=subprocess.PIPE)
                p1.stdout.close()
                p3 = subprocess.Popen(['perl', FLAMEGRAPH_BIN], stdin=p2.stdout, stdout=svg_out)
                p2.stdout.close()
                p3.wait()

            execute('UPDATE bw_flamegraphs SET status=%s, svg_path=%s, perf_data_path=%s WHERE id=%s',
                    ('done', svg_path, local_perf, fg_id))
        except Exception:
            execute('UPDATE bw_flamegraphs SET status=%s WHERE id=%s', ('failed', fg_id))
            raise
```

Updated Task 5 — flamegraph trigger call in `api_flamegraph_trigger`:

```python
# capture app reference before entering thread
_app = app
threading.Thread(
    target=start_flamegraph_job,
    args=(fg_id, device, revision_str, _app),
    daemon=True
).start()
```

### Fix 2: Services page click-through (spec requirement)

Spec says: "Click service → boots where that service was top-5 slowest."

Add filter to the boots route to support `?service=<name>`:

In `boots()` in app.py, add to filter handling:

```python
svc_f = request.args.get('service', '')
if svc_f:
    where_clauses.append(
        'b.id IN (SELECT boot_id FROM bw_blame_entries WHERE service=%s ORDER BY time_s DESC LIMIT 5)'
    )
    args.append(svc_f)
```

In `services.html`, make service name a link:

```html
<td style="font-size:12px">
  <a href="{{ url_for('boots') }}?service={{ svc.service }}">{{ svc.service }}</a>
</td>
```

### Fix 3: Spec table says /api/perf/stat is a separate endpoint

The spec lists `POST /api/perf/stat` as a separate endpoint. The payload format merges perf_stat into `/api/boot`. For completeness, add a standalone endpoint in app.py for devices sending perf stats independently (e.g., devices that POST them outside of boot events):

Add to `create_app()` in app.py:

```python
@app.route('/api/perf/stat', methods=['POST'])
def api_perf_stat():
    data = request.get_json(silent=True) or {}
    required = ['device_ip', 'revision']
    missing = [f for f in required if f not in data]
    if missing:
        return jsonify(error=f'missing: {missing}'), 400
    device_id   = get_or_create_device(data['device_ip'], data.get('device_name', 'device'), '')
    revision_id = get_or_create_revision(data['revision'])
    ps = data.get('perf_stat', data)  # accept flat or nested
    execute(
        'INSERT INTO bw_perf_stats '
        '(device_id, revision_id, duration_s, cycles, instructions, ipc, '
        ' cache_misses, cache_refs, cache_miss_pct, branch_misses, branch_total, branch_miss_pct, raw_output) '
        'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
        (device_id, revision_id,
         ps.get('duration_s', 10), ps.get('cycles'), ps.get('instructions'), ps.get('ipc'),
         ps.get('cache_misses'), ps.get('cache_refs'), ps.get('cache_miss_pct'),
         ps.get('branch_misses'), ps.get('branch_total'), ps.get('branch_miss_pct'),
         ps.get('raw_output', ''))
    )
    return jsonify(ok=True), 201
```

