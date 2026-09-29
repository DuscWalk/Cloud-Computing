"""Business invariants with synthetic vectors. These tests NEVER load face models."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

from conftest import checkin, login, register
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.cleanup import cleanup
from app.config import get_settings
from app.db import get_engine
from app.jobs import process_job, recover_jobs
from app.model_assets import MODEL_VERSION
from app.models import (
    AttendanceEvent,
    AttendanceRecord,
    Counter,
    Photo,
    RecognitionJob,
    User,
    utcnow,
)
from app.vision import Encoding, FaceRejected


def vector(index=0):
    return [float(i == index) for i in range(128)]


class FakeEngine:
    def __init__(self, embedding=None, error=None, callback=None):
        self.embedding = embedding or vector()
        self.error = error
        self.callback = callback

    def encode(self, _path):
        if self.callback:
            self.callback()
        if self.error:
            raise self.error
        return Encoding(self.embedding, 1.0)


def run(job_id, engine=None):
    process_job(job_id, engine=engine or FakeEngine())
    with Session(get_engine()) as db:
        job = db.get(RecognitionJob, job_id)
        return job.result_code if job else None


def enrolled(client, image, username="student01", student_id="2026001", embedding=None):
    response = register(client, image, username, student_id)
    assert response.status_code == 201, response.text
    data = response.json()
    assert run(data["job"]["id"], FakeEngine(embedding)) == "enrolled"
    return data


def test_anonymous_identity_does_not_follow_logged_in_user(client, image, event_id):
    alice = enrolled(client, image)
    bob = enrolled(client, image, "student02", "2026002", vector(1))
    login(client, "student02")
    submitted = checkin(client, image, event_id).json()
    assert run(submitted["id"]) == "checked_in"
    assert client.get("/api/me/attendance").json()["items"] == []
    login(client)
    record = client.get("/api/me/attendance").json()["items"][0]
    assert record["event_name"] == "测试活动"
    with Session(get_engine()) as db:
        saved = db.scalar(select(AttendanceRecord))
        assert saved.user_id == alice["user"]["id"] != bob["user"]["id"]
        assert saved.model_version == MODEL_VERSION
        assert db.get(RecognitionJob, submitted["id"]).user_id is None
        assert db.get(Counter, "recognition_pending").value == 0
    status = client.get(
        f"/api/jobs/{submitted['id']}", headers={"X-Job-Token": submitted["token"]}
    ).json()
    assert status["result"]["name"] == "测***"
    assert "similarity" not in str(status) and "embedding" not in str(status)


def test_unknown_ambiguity_and_duplicate_enrollment(client, image, event_id):
    enrolled(client, image)
    duplicate = register(client, image, "duplicate", "dup").json()
    assert run(duplicate["job"]["id"]) == "face_already_enrolled"
    submitted = checkin(client, image, event_id).json()
    assert run(submitted["id"], FakeEngine(vector(2))) == "unknown_person"
    enrolled(client, image, "student02", "2026002", vector(1))
    ambiguous = vector()
    ambiguous[1] = 1.0
    submitted = checkin(client, image, event_id).json()
    assert run(submitted["id"], FakeEngine(ambiguous)) == "ambiguous_match"
    with Session(get_engine()) as db:
        assert db.scalar(select(func.count()).select_from(AttendanceRecord)) == 0


def test_idempotent_upload_and_concurrent_worker_delivery(client, image, event_id):
    enrolled(client, image)
    key = uuid4().hex
    first = checkin(client, image, event_id, key).json()
    retry = checkin(client, image, event_id, key).json()
    assert retry["id"] == first["id"] and retry["token"] == first["token"]
    with ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(lambda _: process_job(first["id"], FakeEngine()), range(5)))
    second = checkin(client, image, event_id).json()
    assert run(second["id"]) == "already_checked_in"
    with Session(get_engine()) as db:
        assert db.scalar(select(func.count()).select_from(AttendanceRecord)) == 1
        assert db.get(Counter, "recognition_pending").value == 0
        assert db.get(RecognitionJob, first["id"]).attempts == 1
    assert checkin(client, image, "different-event", key).status_code == 409


def test_queue_capacity_failure_and_offline_retry(client, image, event_id, monkeypatch):
    monkeypatch.setattr(get_settings(), "queue_capacity", 1)
    pending = register(client, image).json()
    assert checkin(client, image, event_id).status_code == 429
    assert len(list(get_settings().storage_dir.glob("*.jpg"))) == 1
    assert run(pending["job"]["id"], FakeEngine(error=FaceRejected("no_face"))) == "no_face"
    key = uuid4().hex
    capture = checkin(client, image, event_id, key).json()
    monkeypatch.setattr(get_settings(), "require_worker_ready", True)
    monkeypatch.setattr("app.jobs.worker_ready", lambda: False)
    assert checkin(client, image, event_id, key).json()["id"] == capture["id"]
    assert checkin(client, image, event_id).status_code == 503


def test_model_failure_distinct_from_rejection(client, image):
    response = register(client, image).json()
    assert (
        run(response["job"]["id"], FakeEngine(error=RuntimeError("model broke")))
        == "processing_failed"
    )
    with Session(get_engine()) as db:
        assert db.get(Counter, "recognition_pending").value == 0
        assert db.get(RecognitionJob, response["job"]["id"]).status == "failed"


def test_replacement_is_atomic_and_deleted_templates_stop_matching(client, image, event_id):
    old = enrolled(client, image)
    login(client)
    rejected = client.post(
        "/api/me/photos", files={"photo": ("new.jpg", image, "image/jpeg")}
    ).json()
    assert (
        run(rejected["job"]["id"], FakeEngine(error=FaceRejected("multiple_faces", 2)))
        == "multiple_faces"
    )
    with Session(get_engine()) as db:
        assert db.get(Photo, old["photo"]["id"]).status == "ready"
    replacement = client.post(
        "/api/me/photos", files={"photo": ("new.jpg", image, "image/jpeg")}
    ).json()
    assert run(replacement["job"]["id"], FakeEngine(vector(1))) == "enrolled"
    with Session(get_engine()) as db:
        assert db.get(Photo, old["photo"]["id"]).embedding is None
    assert client.delete(f"/api/me/photos/{replacement['photo']['id']}").status_code == 204
    job = checkin(client, image, event_id).json()
    assert run(job["id"], FakeEngine(vector(1))) == "unknown_person"


def test_deleted_pending_photo_cannot_be_resurrected(client, image):
    data = register(client, image).json()
    login(client)
    engine = FakeEngine(callback=lambda: client.delete(f"/api/me/photos/{data['photo']['id']}"))
    assert run(data["job"]["id"], engine) is None
    with Session(get_engine()) as db:
        assert db.get(Counter, "recognition_pending").value == 0
        assert db.scalar(select(func.count()).select_from(Photo)) == 0


def test_lease_recovery_and_stale_worker_cannot_commit(client, image):
    data = register(client, image).json()
    job_id = data["job"]["id"]

    def expire():
        with Session(get_engine()) as db:
            db.get(RecognitionJob, job_id).lease_expires_at = utcnow() - timedelta(seconds=1)
            db.commit()
        assert recover_jobs() == 1

    assert run(job_id, FakeEngine(callback=expire)) is None
    with Session(get_engine()) as db:
        assert db.get(RecognitionJob, job_id).status == "queued"
        assert db.get(Counter, "recognition_pending").value == 1
    assert run(job_id) == "enrolled"
    with Session(get_engine()) as db:
        assert db.get(RecognitionJob, job_id).attempts == 2
        assert db.get(Counter, "recognition_pending").value == 0


def test_queue_timeout_returns_capacity(client, image):
    data = register(client, image).json()
    with Session(get_engine()) as db:
        db.get(RecognitionJob, data["job"]["id"]).deadline_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert recover_jobs() == 1
    assert recover_jobs() == 0
    with Session(get_engine()) as db:
        assert db.get(Counter, "recognition_pending").value == 0
        assert db.get(RecognitionJob, data["job"]["id"]).result_code == "queue_timeout"


def test_window_uses_receipt_time_and_cleanup_preserves_record(client, image, event_id):
    enrolled(client, image)
    data = checkin(client, image, event_id).json()
    with Session(get_engine()) as db:
        db.get(RecognitionJob, data["id"]).created_at = utcnow() - timedelta(seconds=10)
        db.get(AttendanceEvent, event_id).ends_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert run(data["id"]) == "checked_in"
    with Session(get_engine()) as db:
        db.get(RecognitionJob, data["id"]).expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert cleanup() == 1
    with Session(get_engine()) as db:
        assert db.scalar(select(func.count()).select_from(AttendanceRecord)) == 1


def test_admin_permission_cancellation_and_disable(client, image, event_id):
    owner = enrolled(client, image)
    login(client)
    assert client.get("/api/admin/users").status_code == 403
    with Session(get_engine()) as db:
        db.get(User, owner["user"]["id"]).role = "admin"
        db.commit()
    second = enrolled(client, image, "student02", "2026002", vector(1))
    pending = checkin(client, image, event_id).json()
    assert client.post(f"/api/admin/events/{event_id}/cancel").status_code == 200
    assert run(pending["id"]) == "event_closed"
    assert checkin(client, image, event_id).status_code == 409
    assert (
        client.patch(
            f"/api/admin/users/{second['user']['id']}", json={"status": "disabled"}
        ).status_code
        == 200
    )
    assert login(client, "student02").status_code == 401
    assert client.delete(f"/api/admin/users/{second['user']['id']}").status_code == 204
    assert client.delete(f"/api/admin/users/{owner['user']['id']}").status_code == 409
    with Session(get_engine()) as db:
        assert db.get(Counter, "registered_users").value == 1
        assert db.get(Counter, "recognition_pending").value == 0


def test_reindex_iteration_two_photo(client, image):
    data = register(client, image).json()
    assert run(data["job"]["id"], FakeEngine(error=FaceRejected("no_face"))) == "no_face"
    login(client)
    response = client.post(f"/api/me/photos/{data['photo']['id']}/reindex")
    assert response.status_code == 202
    repeated = client.post(f"/api/me/photos/{data['photo']['id']}/reindex")
    assert response.json()["job"]["id"] == repeated.json()["job"]["id"]
    assert run(response.json()["job"]["id"]) == "enrolled"


def test_out_of_order_enrollment_cannot_replace_newer_template(client, image):
    first = register(client, image).json()
    login(client)
    second = client.post("/api/me/photos", files={"photo": ("new.jpg", image, "image/jpeg")}).json()
    assert run(second["job"]["id"], FakeEngine(vector(1))) == "enrolled"
    assert run(first["job"]["id"]) == "superseded"
    with Session(get_engine()) as db:
        assert db.get(Photo, second["photo"]["id"]).status == "ready"
        assert db.get(Photo, first["photo"]["id"]).status == "rejected"
        assert db.get(User, first["user"]["id"]).active_photo_revision == 2
