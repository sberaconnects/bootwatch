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
