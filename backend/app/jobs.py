"""Durable job state, bounded admission, leases and transaction-safe attendance writes."""

import hashlib
import hmac
import json
import logging
from datetime import timedelta
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_engine
from app.limits import redis_client
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
from app.security import digest
from app.vision import FaceRejected, get_face_engine, rank_identities

log = logging.getLogger(__name__)
PENDING = ("queued", "processing")
WORKER_KEY = "attendance:worker:" + MODEL_VERSION
MESSAGES = {
    "queued": "照片已接收，正在排队处理。",
    "processing": "正在核验人脸，请稍候。",
    "enrolled": "人脸录入成功，可以参加签到。",
    "checked_in": "签到成功。",
    "already_checked_in": "你已完成本次签到，无需重复提交。",
    "unknown_person": "未识别到已录入人员，请先注册并完成人脸录入。",
    "ambiguous_match": "无法可靠确认身份，请正对镜头重新拍摄。",
    "no_face": "未检测到人脸，请正对镜头重新拍摄。",
    "multiple_faces": "检测到多张人脸，请只保留本人入镜。",
    "face_too_small": "人脸太小，请靠近镜头重新拍摄。",
    "blurry_face": "人脸不够清晰，请保持稳定并改善光线。",
    "invalid_image": "无法读取人脸照片，请重新拍摄。",
    "face_already_enrolled": "该人脸已在其他账号录入，请使用原账号或联系管理员。",
    "event_closed": "该活动尚未开始、已结束或已取消。",
    "account_disabled": "账号已停用，请联系管理员。",
    "photo_removed": "照片已删除，本次任务已取消。",
    "superseded": "已有更新的标准照片，本次照片未启用。",
    "queue_timeout": "等待处理超时，请稍后重新提交。",
    "processing_failed": "识别服务处理失败，请稍后重试。",
    "upgrade_required": "系统已升级，请重新核验标准照片。",
    "cancelled": "任务已取消。",
}


def worker_ready() -> bool:
    try:
        data = redis_client().get(WORKER_KEY)
        return bool(data and json.loads(data).get("model_version") == MODEL_VERSION)
    except Exception:
        return False


def require_worker():
    if get_settings().require_worker_ready and not worker_ready():
        raise HTTPException(503, "人脸识别服务正在准备，请稍后重试", headers={"Retry-After": "10"})


def queue_lock(db: Session) -> Counter:
    # This short DB write also provides serialization under SQLite tests. Never infer while locked.
    db.execute(
        update(Counter).where(Counter.name == "recognition_pending").values(value=Counter.value)
    )
    counter = db.scalar(
        select(Counter)
        .where(Counter.name == "recognition_pending")
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if counter is None:
        raise RuntimeError("Run database migrations first")
    return counter


def reserve_slot(db: Session) -> None:
    counter = queue_lock(db)
    if counter.value >= get_settings().queue_capacity:
        raise HTTPException(429, "当前签到人数较多，请稍后重试", headers={"Retry-After": "5"})
    counter.value += 1
    db.flush()


def job_token(job_id: str) -> str:
    return hmac.new(
        get_settings().secret_key.encode(), ("job:" + job_id).encode(), hashlib.sha256
    ).hexdigest()


def create_job(db: Session, photo: Photo, kind: str, event_id=None, idem=None, payload_hash=None):
    if kind == "enrollment":
        user = db.scalar(
            select(User)
            .where(User.id == photo.user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if not user or user.status != "active":
            raise HTTPException(403, "账号已停用")
        user.photo_revision += 1
        photo.revision = user.photo_revision
    now = utcnow()
    job = RecognitionJob(
        id=uuid4().hex,
        photo_id=photo.id,
        user_id=photo.user_id,
        kind=kind,
        status="queued",
        event_id=event_id,
        idempotency_key=idem,
        payload_hash=payload_hash,
        slot_reserved=True,
        deadline_at=now + timedelta(seconds=get_settings().queue_timeout_seconds),
        expires_at=now + timedelta(hours=24),
        created_at=now,
    )
    job.token_hash = digest(job_token(job.id))
    photo.status = "pending"
    photo.reason = None
    db.add(job)
    db.flush()
    return job


def job_view(job: RecognitionJob):
    code = job.result_code or job.status
    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status,
        "result_code": job.result_code,
        "message": MESSAGES.get(code, "请稍后查询处理结果。"),
        "result": job.result,
        "created_at": job.created_at.isoformat() + "Z",
        "completed_at": job.completed_at.isoformat() + "Z" if job.completed_at else None,
    }


def finish(db: Session, job: RecognitionJob, code: str, status="rejected", result=None):
    """Caller holds queue_lock before locking the job; release capacity exactly once."""
    if job.slot_reserved:
        counter = db.get(Counter, "recognition_pending")
        if counter.value < 1:
            raise RuntimeError("Queue counter invariant violated")
        counter.value -= 1
        job.slot_reserved = False
    job.status, job.result_code, job.result = status, code, result
    job.completed_at = utcnow()
    job.lease_token = None
    job.lease_expires_at = None
    photo = db.get(Photo, job.photo_id) if job.photo_id else None
    if photo and photo.status == "pending":
        photo.status = "processed" if status == "succeeded" else "rejected"
        photo.reason = code


def active_templates(db):
    return db.scalars(
        select(Photo)
        .join(User, Photo.user_id == User.id)
        .where(
            Photo.status == "ready",
            User.status == "active",
            Photo.model_version == MODEL_VERSION,
        )
    ).all()


def complete_encoding(db, job, encoding):
    photo = db.get(Photo, job.photo_id) if job.photo_id else None
    if not photo:
        finish(db, job, "photo_removed")
        return
    job.model_version = encoding.model_version
    job.detected_faces, job.feature_dim = encoding.faces, len(encoding.vector)
    job.inference_ms = encoding.inference_ms
    if job.kind == "enrollment":
        user = db.scalar(select(User).where(User.id == job.user_id).with_for_update())
        if not user or user.status != "active":
            finish(db, job, "account_disabled")
            return
        templates = active_templates(db)
        if photo.revision < user.active_photo_revision:
            finish(db, job, "superseded")
            return
        others = [p for p in templates if p.user_id != user.id]
        scores = rank_identities(encoding.vector, others)
        if scores and scores[0][2] >= get_settings().match_threshold:
            finish(db, job, "face_already_enrolled")
            return
        for old in db.scalars(
            select(Photo).where(Photo.user_id == user.id, Photo.status == "ready")
        ):
            if old.id != photo.id:
                old.status, old.embedding = "superseded", None
        user.active_photo_revision = photo.revision
        photo.embedding, photo.model_version, photo.status = (
            encoding.vector,
            encoding.model_version,
            "ready",
        )
        photo.reason = None
        finish(db, job, "enrolled", "succeeded")
        return

    event = db.scalar(
        select(AttendanceEvent).where(AttendanceEvent.id == job.event_id).with_for_update()
    )
    # Queueing must not move a timely upload outside the attendance window.
    if (
        not event
        or event.status != "active"
        or not (event.starts_at <= job.created_at <= event.ends_at)
    ):
        finish(db, job, "event_closed")
        return
    ranked = rank_identities(encoding.vector, active_templates(db))
    if not ranked or ranked[0][2] < get_settings().match_threshold:
        finish(db, job, "unknown_person")
        return
    if len(ranked) > 1 and ranked[0][2] - ranked[1][2] < get_settings().match_margin:
        finish(db, job, "ambiguous_match")
        return
    user_id, photo_id, score = ranked[0]
    user = db.scalar(select(User).where(User.id == user_id).with_for_update())
    template = db.get(Photo, photo_id)
    if (
        user.status != "active"
        or template.status != "ready"
        or template.model_version != MODEL_VERSION
    ):
        finish(db, job, "unknown_person")
        return
    record = db.scalar(
        select(AttendanceRecord).where(
            AttendanceRecord.event_id == event.id,
            AttendanceRecord.user_id == user.id,
        )
    )
    code = "already_checked_in" if record else "checked_in"
    if not record:
        record = AttendanceRecord(
            event_id=event.id,
            user_id=user.id,
            checked_at=job.created_at,
            similarity=score,
            source_job_id=job.id,
            model_version=MODEL_VERSION,
            template_id=photo_id,
            template_revision=template.revision,
        )
        db.add(record)
        db.flush()
    masked = user.name[:1] + "*" * max(1, len(user.name) - 1)
    finish(
        db,
        job,
        code,
        "succeeded",
        {
            "name": masked,
            "event_name": event.name,
            "checked_at": record.checked_at.isoformat() + "Z",
        },
    )


def process_job(job_id: str, engine=None):
    lease = uuid4().hex
    with Session(get_engine(), expire_on_commit=False) as db:
        now = utcnow()
        claimed = db.execute(
            update(RecognitionJob)
            .where(
                RecognitionJob.id == job_id,
                RecognitionJob.status == "queued",
                RecognitionJob.deadline_at > now,
            )
            .values(
                status="processing",
                started_at=now,
                lease_token=lease,
                lease_expires_at=now + timedelta(seconds=get_settings().worker_lease_seconds),
                attempts=RecognitionJob.attempts + 1,
            )
        )
        if claimed.rowcount != 1:
            return
        db.commit()
        job = db.get(RecognitionJob, job_id)
        photo = db.get(Photo, job.photo_id) if job.photo_id else None
        path = get_settings().storage_dir / photo.storage_key if photo else None
    encoding, rejection = None, None
    try:
        if path is None:
            raise FaceRejected("photo_removed")
        encoding = (engine or get_face_engine()).encode(path)
    except FaceRejected as exc:
        rejection = exc
    except Exception:
        # Never pretend an unavailable/broken model is an unregistered person.
        log.exception("Model execution failed for job %s", job_id)
        rejection = FaceRejected("processing_failed")
    with Session(get_engine()) as db:
        queue_lock(db)
        job = db.scalar(select(RecognitionJob).where(RecognitionJob.id == job_id).with_for_update())
        if not job or job.status != "processing" or job.lease_token != lease:
            return
        if rejection:
            job.detected_faces = rejection.faces
            finish(
                db,
                job,
                rejection.code,
                "failed" if rejection.code == "processing_failed" else "rejected",
            )
        else:
            complete_encoding(db, job, encoding)
        db.commit()
        log.info(
            "job=%s code=%s model=%s faces=%s dim=%s inference_ms=%s",
            job.id,
            job.result_code,
            job.model_version,
            job.detected_faces,
            job.feature_dim,
            job.inference_ms,
        )


def recover_jobs() -> int:
    recovered = 0
    now = utcnow()
    with Session(get_engine()) as db:
        queue_lock(db)
        jobs = db.scalars(
            select(RecognitionJob).where(RecognitionJob.status.in_(PENDING)).with_for_update()
        ).all()
        for job in jobs:
            if job.status == "processing" and job.lease_expires_at and job.lease_expires_at > now:
                continue
            if (
                not job.deadline_at
                or job.deadline_at <= now
                or job.attempts >= get_settings().max_job_attempts
            ):
                finish(
                    db,
                    job,
                    "queue_timeout" if job.status == "queued" else "processing_failed",
                    "failed",
                )
                recovered += 1
            elif job.status == "processing":
                job.status, job.lease_token, job.lease_expires_at = "queued", None, None
                job.dispatched_at = None
                recovered += 1
        db.commit()
    return recovered
