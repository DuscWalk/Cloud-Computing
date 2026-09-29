"""Administrator routes: no implicit first-user administrator or public bootstrap."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.jobs import MESSAGES, PENDING, finish, queue_lock, worker_ready
from app.model_assets import MODEL_VERSION
from app.models import (
    AttendanceEvent,
    AttendanceRecord,
    Counter,
    Photo,
    RecognitionJob,
    User,
    UserSession,
    utcnow,
)
from app.schemas import EventData, UserState
from app.security import admin_user, require_csrf
from app.storage import remove_image

router = APIRouter(prefix="/api/admin", dependencies=[Depends(admin_user)])
DB = Annotated[Session, Depends(get_db)]
Admin = Annotated[User, Depends(admin_user)]
Unsafe = [Depends(require_csrf)]


@router.get("/overview")
def overview(db: DB):
    return {
        "worker_ready": worker_ready(),
        "model_version": MODEL_VERSION,
        "pending_jobs": db.get(Counter, "recognition_pending").value,
        "queue_capacity": get_settings().queue_capacity,
        "users": db.scalar(select(func.count()).select_from(User)),
        "ready_templates": db.scalar(
            select(func.count()).select_from(Photo).where(Photo.status == "ready")
        ),
        "records": db.scalar(select(func.count()).select_from(AttendanceRecord)),
    }


@router.get("/users")
def users(db: DB):
    return {
        "items": [
            {
                "id": u.id,
                "name": u.name,
                "username": u.username,
                "student_id": u.student_id,
                "role": u.role,
                "status": u.status,
                "enrolled": bool(
                    db.scalar(
                        select(Photo.id)
                        .where(
                            Photo.user_id == u.id,
                            Photo.status == "ready",
                            Photo.model_version == MODEL_VERSION,
                        )
                        .limit(1)
                    )
                ),
            }
            for u in db.scalars(select(User).order_by(User.created_at))
        ]
    }


@router.patch("/users/{user_id}", dependencies=Unsafe)
def set_user_state(user_id: str, data: UserState, actor: Admin, db: DB):
    queue_lock(db)
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "账号不存在")
    if user.id == actor.id or user.role == "admin":
        raise HTTPException(409, "管理员账号需要通过服务器命令管理")
    user.status = data.status
    if data.status == "disabled":
        db.execute(delete(UserSession).where(UserSession.user_id == user.id))
        for job in db.scalars(
            select(RecognitionJob).where(
                RecognitionJob.user_id == user.id, RecognitionJob.status.in_(PENDING)
            )
        ):
            finish(db, job, "account_disabled")
    db.commit()
    return {"status": user.status}


def erase_photo(db: Session, photo: Photo):
    for job in db.scalars(select(RecognitionJob).where(RecognitionJob.photo_id == photo.id)):
        if job.status in PENDING:
            finish(db, job, "photo_removed")
    db.flush()
    db.execute(delete(RecognitionJob).where(RecognitionJob.photo_id == photo.id))
    db.delete(photo)


@router.delete("/users/{user_id}", status_code=204, dependencies=Unsafe)
def delete_user(user_id: str, actor: Admin, db: DB):
    queue_lock(db)
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "账号不存在")
    if user.id == actor.id or user.role == "admin":
        raise HTTPException(409, "不能通过页面删除管理员账号")
    photos = list(db.scalars(select(Photo).where(Photo.user_id == user.id)))
    keys = [p.storage_key for p in photos]
    for photo in photos:
        erase_photo(db, photo)
    db.execute(delete(RecognitionJob).where(RecognitionJob.user_id == user.id))
    db.execute(delete(AttendanceRecord).where(AttendanceRecord.user_id == user.id))
    db.execute(delete(UserSession).where(UserSession.user_id == user.id))
    db.execute(
        update(AttendanceEvent).where(AttendanceEvent.created_by == user.id).values(created_by=None)
    )
    db.flush()
    db.delete(user)
    db.get(Counter, "registered_users").value -= 1
    db.commit()
    for key in keys:
        remove_image(key)


@router.get("/users/{user_id}/photos")
def user_photos(user_id: str, db: DB):
    if not db.get(User, user_id):
        raise HTTPException(404, "账号不存在")
    return {
        "items": [
            {
                "id": p.id,
                "status": p.status,
                "created_at": p.created_at.isoformat() + "Z",
                "reason": MESSAGES.get(p.reason) if p.reason else None,
            }
            for p in db.scalars(
                select(Photo).where(Photo.user_id == user_id).order_by(Photo.created_at.desc())
            )
        ]
    }


@router.get("/photos/{photo_id}")
def private_photo(photo_id: str, db: DB):
    photo = db.get(Photo, photo_id)
    if not photo or not photo.user_id:
        raise HTTPException(404, "照片不存在")
    path = get_settings().storage_dir / photo.storage_key
    if not path.is_file():
        raise HTTPException(404, "照片不存在")
    return FileResponse(path, media_type="image/jpeg")


@router.delete("/photos/{photo_id}", status_code=204, dependencies=Unsafe)
def remove_photo(photo_id: str, db: DB):
    queue_lock(db)
    photo = db.get(Photo, photo_id)
    if not photo or not photo.user_id:
        raise HTTPException(404, "照片不存在")
    key = photo.storage_key
    erase_photo(db, photo)
    db.commit()
    remove_image(key)


@router.get("/events")
def events(db: DB):
    return {
        "items": [
            {
                "id": e.id,
                "name": e.name,
                "starts_at": e.starts_at.isoformat() + "Z",
                "ends_at": e.ends_at.isoformat() + "Z",
                "status": e.status,
                "count": db.scalar(
                    select(func.count())
                    .select_from(AttendanceRecord)
                    .where(AttendanceRecord.event_id == e.id)
                ),
            }
            for e in db.scalars(
                select(AttendanceEvent).order_by(AttendanceEvent.starts_at.desc()).limit(100)
            )
        ]
    }


@router.post("/events", status_code=201, dependencies=Unsafe)
def create_event(data: EventData, user: Admin, db: DB):
    if data.ends_at.replace(tzinfo=None) <= utcnow():
        raise HTTPException(422, "结束时间必须晚于当前时间")
    event = AttendanceEvent(
        name=data.name,
        starts_at=data.starts_at.replace(tzinfo=None),
        ends_at=data.ends_at.replace(tzinfo=None),
        created_by=user.id,
    )
    db.add(event)
    db.commit()
    return {"id": event.id, "name": event.name}


@router.post("/events/{event_id}/cancel", dependencies=Unsafe)
def cancel_event(event_id: str, db: DB):
    queue_lock(db)
    event = db.get(AttendanceEvent, event_id)
    if not event:
        raise HTTPException(404, "活动不存在")
    event.status = "cancelled"
    for job in db.scalars(
        select(RecognitionJob).where(
            RecognitionJob.event_id == event.id, RecognitionJob.status.in_(PENDING)
        )
    ):
        finish(db, job, "event_closed")
    db.commit()
    return {"status": event.status}


@router.get("/events/{event_id}/records")
def event_records(event_id: str, db: DB):
    if not db.get(AttendanceEvent, event_id):
        raise HTTPException(404, "活动不存在")
    rows = db.execute(
        select(AttendanceRecord, User)
        .join(User)
        .where(AttendanceRecord.event_id == event_id)
        .order_by(AttendanceRecord.checked_at)
    ).all()
    return {
        "items": [
            {
                "id": r.id,
                "name": u.name,
                "student_id": u.student_id,
                "checked_at": r.checked_at.isoformat() + "Z",
            }
            for r, u in rows
        ]
    }
