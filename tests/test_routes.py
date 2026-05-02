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
