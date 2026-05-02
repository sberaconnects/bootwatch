import pytest
import os

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
