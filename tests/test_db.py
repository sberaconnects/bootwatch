from db import get_or_create_device, get_or_create_revision

def test_get_or_create_device_returns_id(app):
    with app.app_context():
        device_id = get_or_create_device("192.168.99.1", "test-dev", "test-label")
        assert isinstance(device_id, int)
        assert device_id > 0
        # second call returns same id (idempotent)
        device_id2 = get_or_create_device("192.168.99.1", "test-dev", "test-label")
        assert device_id == device_id2

def test_get_or_create_revision_returns_id(app):
    with app.app_context():
        rev_id = get_or_create_revision("v1.0.0-test")
        assert isinstance(rev_id, int)
        rev_id2 = get_or_create_revision("v1.0.0-test")
        assert rev_id == rev_id2
