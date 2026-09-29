import hashlib
import secrets
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import ValidationError
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.admin_api import router as admin_router
from app.config import get_settings
from app.db import get_db
from app.jobs import (
    MESSAGES,
    PENDING,
    create_job,
    finish,
    job_token,
    job_view,
    queue_lock,
    require_worker,
    reserve_slot,
    worker_ready,
)
from app.limits import limit, redis_client
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
from app.schemas import LoginData, RegisterData
from app.security import (
    DUMMY_HASH,
    SESSION_COOKIE,
    create_session,
    current_user,
    digest,
    hasher,
    issue_csrf,
    optional_user,
    require_csrf,
    verify_password,
)
from app.storage import remove_image, save_image


@asynccontextmanager
async def lifespan(_app: FastAPI):
    get_settings().storage_dir.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(
    title="南大人脸签到",
    version="0.3.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)
DB = Annotated[Session, Depends(get_db)]
Authenticated = Annotated[User, Depends(current_user)]
Unsafe = [Depends(require_csrf)]
app.include_router(admin_router)


@app.exception_handler(RequestValidationError)
async def validation_error(_request, exc):
    # Never echo submitted passwords or other input values in error responses.
    return JSONResponse(
        status_code=422,
        content={
            "detail": "请检查填写的信息",
            "errors": [
                {"field": ".".join(map(str, err["loc"])), "message": err["msg"]}
                for err in exc.errors()
            ],
        },
    )


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Cache-Control"] = "no-store"
    return response


def user_view(user: User):
    return {
        "id": user.id,
        "name": user.name,
        "username": user.username,
        "student_id": user.student_id,
        "role": user.role,
        "status": user.status,
    }


def photo_view(photo: Photo):
    return {
        "id": photo.id,
        "status": "uploaded"
        if photo.status == "ready" and photo.model_version != MODEL_VERSION
        else photo.status,
        "purpose": photo.purpose,
        "width": photo.width,
        "height": photo.height,
        "created_at": photo.created_at.isoformat() + "Z",
        "reason": MESSAGES.get(photo.reason, "") if photo.reason else None,
    }


def new_photo_job(db: Session, key: str, width: int, height: int, user_id: str | None, kind: str):
    photo = Photo(user_id=user_id, storage_key=key, purpose=kind, width=width, height=height)
    db.add(photo)
    db.flush()
    job = create_job(db, photo, kind)
    return photo, job, job_token(job.id)


@app.get("/api/health/live")
def live():
    return {"status": "ok", "version": "0.3.0", "recognition_enabled": True}


@app.get("/api/health/ready")
def ready(db: DB):
    try:
        db.execute(select(Counter).limit(1))  # Requires migrations, not just a reachable DB.
        if get_settings().redis_url:
            redis_client().ping()
    except Exception:
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    loaded = worker_ready()
    if get_settings().require_worker_ready and not loaded:
        return JSONResponse(
            status_code=503, content={"status": "worker_unavailable", "recognition_enabled": False}
        )
    return {"status": "ready", "recognition_enabled": loaded, "model_version": MODEL_VERSION}


@app.get("/api/auth/csrf")
def csrf(response: Response):
    return {"csrf_token": issue_csrf(response)}


@app.post("/api/auth/register", status_code=201, dependencies=Unsafe)
def register(
    request: Request,
    db: DB,
    name: Annotated[str, Form()],
    student_id: Annotated[str, Form()],
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    consent: Annotated[bool, Form()],
    photo: Annotated[UploadFile, File()],
):
    limit(request, "register", 20)
    require_worker()
    try:
        data = RegisterData(
            name=name, student_id=student_id, username=username, password=password, consent=consent
        )
    except ValidationError as exc:
        raise HTTPException(422, "请检查姓名、学号、账号、密码及照片使用同意项") from exc
    key, width, height = save_image(photo)
    try:
        reserve_slot(db)
        result = db.execute(
            update(Counter)
            .where(Counter.name == "registered_users", Counter.value < get_settings().max_users)
            .values(value=Counter.value + 1)
        )
        if result.rowcount != 1:
            raise HTTPException(409, "人员库已满，请联系管理员")
        user = User(
            name=data.name,
            student_id=data.student_id,
            username=data.username.lower(),
            password_hash=hasher.hash(data.password),
        )
        db.add(user)
        db.flush()
        picture, job, token = new_photo_job(db, key, width, height, user.id, "enrollment")
        db.commit()
    except Exception as exc:
        db.rollback()
        remove_image(key)
        if isinstance(exc, IntegrityError):
            raise HTTPException(409, "账号或学号已存在") from exc
        raise
    return {
        "user": user_view(user),
        "photo": photo_view(picture),
        "job": {**job_view(job), "token": token},
    }


@app.post("/api/auth/login", dependencies=Unsafe)
def login(request: Request, response: Response, data: LoginData, db: DB):
    limit(request, "login", 20)
    user = db.scalar(select(User).where(User.username == data.username.strip().lower()))
    valid = verify_password(data.password, user.password_hash if user else DUMMY_HASH)
    if not valid or user is None or user.status != "active":
        raise HTTPException(401, "账号或密码错误")
    # Replace this browser's existing session and clear expired sessions.
    old = request.cookies.get(SESSION_COOKIE)
    if old:
        db.execute(delete(UserSession).where(UserSession.token_hash == digest(old)))
    db.execute(delete(UserSession).where(UserSession.expires_at <= utcnow()))
    create_session(response, db, user)
    db.commit()
    return {"user": user_view(user)}


@app.post("/api/auth/logout", status_code=204, dependencies=Unsafe)
def logout(request: Request, response: Response, db: DB):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        db.execute(delete(UserSession).where(UserSession.token_hash == digest(token)))
        db.commit()
    response.delete_cookie(
        SESSION_COOKIE,
        path="/api",
        secure=get_settings().cookie_secure,
        httponly=True,
        samesite="lax",
    )


@app.get("/api/me")
def me(user: Authenticated):
    return user_view(user)


@app.get("/api/me/photos")
def photos(user: Authenticated, db: DB):
    pictures = db.scalars(
        select(Photo).where(Photo.user_id == user.id).order_by(Photo.created_at.desc())
    ).all()
    items = []
    for picture in pictures:
        job = db.scalar(
            select(RecognitionJob)
            .where(RecognitionJob.photo_id == picture.id)
            .order_by(RecognitionJob.created_at.desc())
            .limit(1)
        )
        items.append({**photo_view(picture), "job": job_view(job) if job else None})
    return {"items": items}


@app.post("/api/me/photos", status_code=202, dependencies=Unsafe)
def upload_standard(
    request: Request, user: Authenticated, db: DB, photo: Annotated[UploadFile, File()]
):
    limit(request, "standard-upload", 20)
    require_worker()
    key, width, height = save_image(photo)
    try:
        reserve_slot(db)
        current = db.scalar(
            select(User)
            .where(User.id == user.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if current.status != "active":
            raise HTTPException(403, "账号已停用")
        if len(db.scalars(select(Photo.id).where(Photo.user_id == user.id)).all()) >= 5:
            raise HTTPException(409, "每人最多保留 5 张照片，请先删除无用照片")
        picture, job, token = new_photo_job(db, key, width, height, user.id, "enrollment")
        db.commit()
    except Exception:
        db.rollback()
        remove_image(key)
        raise
    return {"photo": photo_view(picture), "job": {**job_view(job), "token": token}}


@app.post("/api/me/photos/{photo_id}/reindex", status_code=202, dependencies=Unsafe)
def reindex_photo(photo_id: str, user: Authenticated, db: DB):
    require_worker()
    queue_lock(db)
    photo = db.get(Photo, photo_id)
    if not photo or photo.user_id != user.id:
        raise HTTPException(404, "照片不存在")
    pending = db.scalar(
        select(RecognitionJob).where(
            RecognitionJob.photo_id == photo.id, RecognitionJob.status.in_(PENDING)
        )
    )
    if pending:
        return {"job": {**job_view(pending), "token": job_token(pending.id)}}
    if photo.status == "ready" and photo.model_version == MODEL_VERSION:
        raise HTTPException(409, "该照片已经完成录入")
    reserve_slot(db)
    job = create_job(db, photo, "enrollment")
    db.commit()
    return {"job": {**job_view(job), "token": job_token(job.id)}}


@app.get("/api/photos/{photo_id}")
def photo_file(photo_id: str, user: Authenticated, db: DB):
    photo = db.get(Photo, photo_id)
    if not photo or photo.user_id != user.id:
        raise HTTPException(404, "照片不存在")
    path = get_settings().storage_dir / photo.storage_key
    if not path.is_file():
        raise HTTPException(404, "照片不存在")
    return FileResponse(path, media_type="image/jpeg")


@app.delete("/api/me/photos/{photo_id}", status_code=204, dependencies=Unsafe)
def delete_photo(photo_id: str, user: Authenticated, db: DB):
    queue_lock(db)
    photo = db.get(Photo, photo_id)
    if not photo or photo.user_id != user.id:
        raise HTTPException(404, "照片不存在")
    key = photo.storage_key
    for job in db.scalars(select(RecognitionJob).where(RecognitionJob.photo_id == photo.id)):
        if job.status in PENDING:
            finish(db, job, "photo_removed")
    db.flush()
    db.execute(delete(RecognitionJob).where(RecognitionJob.photo_id == photo.id))
    db.delete(photo)
    db.commit()
    remove_image(key)


@app.post("/api/uploads", status_code=202, dependencies=Unsafe)
def upload(
    request: Request,
    db: DB,
    photo: Annotated[UploadFile, File()],
    event_id: Annotated[str, Form(max_length=32)],
    idempotency_key: Annotated[
        str, Header(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    ],
):
    limit(request, "anonymous-upload", 180)
    received_at = utcnow()
    key, width, height = save_image(photo)
    try:
        fingerprint = hashlib.sha256((get_settings().storage_dir / key).read_bytes()).hexdigest()
        idem = digest("capture:" + idempotency_key)
        queue_lock(db)
        existing = db.scalar(select(RecognitionJob).where(RecognitionJob.idempotency_key == idem))
        if existing:
            if existing.payload_hash != fingerprint or existing.event_id != event_id:
                raise HTTPException(409, "重复请求与原照片或活动不一致，请重新选择照片")
            result = {**job_view(existing), "token": job_token(existing.id)}
            db.commit()
            remove_image(key)
            return result
        require_worker()
        event = db.get(AttendanceEvent, event_id)
        if (
            not event
            or event.status != "active"
            or not (event.starts_at <= received_at <= event.ends_at)
        ):
            raise HTTPException(409, "该活动尚未开始、已结束或已取消")
        reserve_slot(db)
        picture = Photo(storage_key=key, purpose="capture", width=width, height=height)
        db.add(picture)
        db.flush()
        job = create_job(db, picture, "capture", event_id, idem, fingerprint)
        job.created_at = received_at
        db.commit()
    except Exception:
        db.rollback()
        remove_image(key)
        raise
    return {**job_view(job), "token": job_token(job.id)}


@app.get("/api/jobs/{job_id}")
def job_status(
    job_id: str, request: Request, db: DB, user: Annotated[User | None, Depends(optional_user)]
):
    job = db.get(RecognitionJob, job_id)
    if not job:
        raise HTTPException(404, "任务不存在或已过期")
    owner = user is not None and job.user_id == user.id
    token = request.headers.get("X-Job-Token", "")
    allowed = job.expires_at > utcnow() and secrets.compare_digest(digest(token), job.token_hash)
    if not owner and not allowed:
        raise HTTPException(404, "任务不存在或已过期")
    return job_view(job)


@app.get("/api/me/attendance")
def attendance(user: Authenticated, db: DB):
    records = db.scalars(
        select(AttendanceRecord)
        .where(AttendanceRecord.user_id == user.id)
        .order_by(AttendanceRecord.checked_at.desc())
    ).all()
    return {
        "items": [
            {
                "id": r.id,
                "event_id": r.event_id,
                "event_name": db.get(AttendanceEvent, r.event_id).name,
                "checked_at": r.checked_at.isoformat() + "Z",
            }
            for r in records
        ]
    }


def event_view(event: AttendanceEvent):
    now = utcnow()
    phase = (
        "cancelled"
        if event.status == "cancelled"
        else ("upcoming" if now < event.starts_at else "ended" if now > event.ends_at else "open")
    )
    return {
        "id": event.id,
        "name": event.name,
        "status": event.status,
        "phase": phase,
        "starts_at": event.starts_at.isoformat() + "Z",
        "ends_at": event.ends_at.isoformat() + "Z",
    }


@app.get("/api/events")
def events(db: DB):
    rows = db.scalars(
        select(AttendanceEvent)
        .where(AttendanceEvent.status == "active", AttendanceEvent.ends_at >= utcnow())
        .order_by(AttendanceEvent.starts_at)
        .limit(100)
    )
    return {"items": [event_view(event) for event in rows]}


@app.get("/api/events/{event_id}")
def event_detail(event_id: str, db: DB):
    event = db.get(AttendanceEvent, event_id)
    if not event:
        raise HTTPException(404, "活动不存在")
    return event_view(event)


@app.exception_handler(SQLAlchemyError)
async def database_error(_request, _exc):
    return JSONResponse(status_code=503, content={"detail": "数据服务暂时不可用，请稍后重试"})
