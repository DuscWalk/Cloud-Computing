import io

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from PIL import Image

from app.config import get_settings
from app.db import get_engine
from app.limits import redis_client


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("APP_STORAGE_DIR", str(tmp_path / "photos"))
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("APP_COOKIE_SECURE", "false")
    monkeypatch.setenv("APP_REDIS_URL", "")
    monkeypatch.setenv("APP_RATE_LIMIT_ENABLED", "false")
    get_settings.cache_clear()
    get_engine.cache_clear()
    redis_client.cache_clear()
    command.upgrade(Config("alembic.ini"), "head")
    from app.main import app

    with TestClient(app) as test_client:
        token = test_client.get("/api/auth/csrf").json()["csrf_token"]
        test_client.headers["X-CSRF-Token"] = token
        yield test_client
    get_engine().dispose()
    get_engine.cache_clear()
    get_settings.cache_clear()


@pytest.fixture
def image():
    output = io.BytesIO()
    Image.new("RGB", (200, 240), color=(80, 120, 160)).save(output, format="JPEG")
    return output.getvalue()


def register(client, image, username="student01", student_id="2026001"):
    return client.post(
        "/api/auth/register",
        data={
            "name": "测试同学",
            "student_id": student_id,
            "username": username,
            "password": "test-password-2026",
            "consent": "true",
        },
        files={"photo": ("photo.jpg", image, "image/jpeg")},
    )


def login(client, username="student01"):
    return client.post(
        "/api/auth/login",
        json={
            "username": username,
            "password": "test-password-2026",
        },
    )
