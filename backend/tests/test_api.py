from datetime import timedelta

from conftest import login, register
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.cleanup import cleanup
from app.config import get_settings
from app.db import get_engine
from app.models import Counter, Photo, RecognitionJob, User, UserSession, utcnow


def test_register_login_logout_and_persistence(client, image):
    data = register(client, image)
    assert data.status_code == 201
    assert data.json()["photo"]["status"] == "uploaded"
    assert "password" not in data.text
    assert client.get("/api/me").status_code == 401
    assert login(client).status_code == 200
    session_cookie = client.cookies.get("attendance_session")
    assert client.get("/api/me").json()["student_id"] == "2026001"
    photo_id = data.json()["photo"]["id"]
    assert client.get(f"/api/photos/{photo_id}").status_code == 200
    with Session(get_engine()) as db:
        user = db.scalar(select(User))
        assert user.password_hash.startswith("$argon2id$")
        assert user.password_hash != "test-password-2026"
        assert db.scalar(select(func.count()).select_from(Photo)) == 1
        assert db.scalar(select(func.count()).select_from(UserSession)) == 1
    assert client.post("/api/auth/logout").status_code == 204
    client.cookies.set("attendance_session", session_cookie)
    assert client.get("/api/me").status_code == 401


def test_duplicate_registration_is_atomic(client, image):
    assert register(client, image).status_code == 201
    assert register(client, image).status_code == 409
    with Session(get_engine()) as db:
        assert db.get(Counter, "registered_users").value == 1
        assert db.scalar(select(func.count()).select_from(User)) == 1
    assert len(list(get_settings().storage_dir.glob("*.jpg"))) == 1


def test_csrf_and_invalid_images(client, image):
    client.headers.pop("X-CSRF-Token")
    assert register(client, image).status_code == 403
    client.headers["X-CSRF-Token"] = client.get("/api/auth/csrf").json()["csrf_token"]
    response = register(client, b"not-an-image")
    assert response.status_code == 422
    assert list(get_settings().storage_dir.glob("*.jpg")) == []


def test_upload_size_and_pixel_limits(client, image, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_upload_bytes", 100)
    assert register(client, image).status_code == 413
    monkeypatch.setattr(get_settings(), "max_upload_bytes", 5 * 1024 * 1024)
    monkeypatch.setattr(get_settings(), "max_image_pixels", 100)
    assert register(client, image).status_code == 422


def test_photo_and_job_access_isolation(client, image):
    first = register(client, image).json()
    assert register(client, image, "student02", "2026002").status_code == 201
    assert login(client, "student02").status_code == 200
    photo_id = first["photo"]["id"]
    assert client.get(f"/api/photos/{photo_id}").status_code == 404
    assert client.delete(f"/api/me/photos/{photo_id}").status_code == 404
    assert client.get(f"/api/jobs/{first['job']['id']}").status_code == 404
    assert (
        client.get(
            f"/api/jobs/{first['job']['id']}",
            headers={
                "X-Job-Token": first["job"]["token"],
            },
        ).status_code
        == 200
    )


def test_anonymous_upload_and_cleanup(client, image):
    response = client.post("/api/uploads", files={"photo": ("photo.jpg", image, "image/jpeg")})
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "uploaded"
    assert client.get(f"/api/jobs/{data['id']}").status_code == 404
    assert (
        client.get(f"/api/jobs/{data['id']}", headers={"X-Job-Token": data["token"]}).status_code
        == 200
    )
    with Session(get_engine()) as db:
        db.get(RecognitionJob, data["id"]).expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert cleanup() == 1
    assert (
        client.get(f"/api/jobs/{data['id']}", headers={"X-Job-Token": data["token"]}).status_code
        == 404
    )
    assert list(get_settings().storage_dir.glob("*.jpg")) == []


def test_photo_delete_removes_job_and_file(client, image):
    data = register(client, image).json()
    login(client)
    assert client.delete(f"/api/me/photos/{data['photo']['id']}").status_code == 204
    assert client.get("/api/me/photos").json() == {"items": []}
    assert list(get_settings().storage_dir.glob("*.jpg")) == []


def test_user_capacity(client, image, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_users", 1)
    assert register(client, image).status_code == 201
    assert register(client, image, "student02", "2026002").status_code == 409
    assert len(list(get_settings().storage_dir.glob("*.jpg"))) == 1


def test_password_validation_never_echoes_input(client):
    response = client.post("/api/auth/login", json={"username": "user", "password": "x" * 200})
    assert response.status_code == 422
    assert "x" * 200 not in response.text
