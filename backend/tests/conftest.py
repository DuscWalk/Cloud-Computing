import io
from datetime import timedelta
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_engine
from app.limits import redis_client
from app.models import AttendanceEvent, utcnow


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("APP_STORAGE_DIR", str(tmp_path / "photos"))
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("APP_COOKIE_SECURE", "false")
    monkeypatch.setenv("APP_REDIS_URL", "")
    monkeypatch.setenv("APP_RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("APP_REQUIRE_WORKER_READY", "false")
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


@pytest.fixture
def event_id(client):
    with Session(get_engine()) as db:
        event = AttendanceEvent(
            name="测试活动",
            starts_at=utcnow() - timedelta(hours=1),
            ends_at=utcnow() + timedelta(hours=1),
        )
        db.add(event)
        db.commit()
        return event.id


def checkin(client, image, event_id, key=None):
    return client.post(
        "/api/uploads",
        data={"event_id": event_id},
        headers={"Idempotency-Key": key or uuid4().hex},
        files={"photo": ("photo.jpg", image, "image/jpeg")},
    )
