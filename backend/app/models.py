from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def new_id() -> str:
    return uuid4().hex


def utcnow() -> datetime:
    # Naive UTC is portable across MySQL and SQLite; API serializes it explicitly as UTC.
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(32), unique=True)
    student_id: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(40))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="user")
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active")
    photo_revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    active_photo_revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class UserSession(Base):
    __tablename__ = "user_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class Photo(Base):
    __tablename__ = "face_templates"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    storage_key: Mapped[str] = mapped_column(String(64), unique=True)
    purpose: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="uploaded")
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    model_version: Mapped[str | None] = mapped_column(String(100))
    embedding: Mapped[list | None] = mapped_column(JSON)
    reason: Mapped[str | None] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class RecognitionJob(Base):
    __tablename__ = "recognition_jobs"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_job_idempotency"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    photo_id: Mapped[str | None] = mapped_column(ForeignKey("face_templates.id"), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="uploaded")
    event_id: Mapped[str | None] = mapped_column(
        ForeignKey("attendance_events.id", name="fk_job_event"), index=True
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(64))
    payload_hash: Mapped[str | None] = mapped_column(String(64))
    result_code: Mapped[str | None] = mapped_column(String(40))
    result: Mapped[dict | None] = mapped_column(JSON)
    model_version: Mapped[str | None] = mapped_column(String(100))
    detected_faces: Mapped[int | None] = mapped_column(Integer)
    feature_dim: Mapped[int | None] = mapped_column(Integer)
    inference_ms: Mapped[float | None] = mapped_column(Float)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    slot_reserved: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    lease_token: Mapped[str | None] = mapped_column(String(32))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class Counter(Base):
    __tablename__ = "system_counters"
    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    value: Mapped[int] = mapped_column(Integer, default=0)


class AttendanceEvent(Base):
    __tablename__ = "attendance_events"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(100))
    starts_at: Mapped[datetime] = mapped_column(DateTime)
    ends_at: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active")
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", name="fk_event_creator"))


class AttendanceRecord(Base):
    __tablename__ = "attendance_records"
    __table_args__ = (UniqueConstraint("event_id", "user_id", name="uq_event_user"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    event_id: Mapped[str] = mapped_column(ForeignKey("attendance_events.id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    similarity: Mapped[float | None] = mapped_column(Float)
    model_version: Mapped[str | None] = mapped_column(String(100))
    # Audit references survive removal of temporary jobs and old templates.
    source_job_id: Mapped[str | None] = mapped_column(String(32))
    template_id: Mapped[str | None] = mapped_column(String(32))
    template_revision: Mapped[int | None] = mapped_column(Integer)
