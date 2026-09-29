import secrets
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import ValidationError
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.limits import limit, redis_client
from app.models import AttendanceRecord, Counter, Photo, RecognitionJob, User, UserSession, utcnow
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
    version="0.2.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)
DB = Annotated[Session, Depends(get_db)]
Authenticated = Annotated[User, Depends(current_user)]
Unsafe = [Depends(require_csrf)]
UPLOAD_MESSAGE = "照片已保存，尚未完成身份核验。"


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
    }


def photo_view(photo: Photo):
    return {
        "id": photo.id,
        "status": photo.status,
        "purpose": photo.purpose,
        "width": photo.width,
        "height": photo.height,
        "created_at": photo.created_at.isoformat() + "Z",
    }


def new_photo_job(db: Session, key: str, width: int, height: int, user_id: str | None, kind: str):
    photo = Photo(user_id=user_id, storage_key=key, purpose=kind, width=width, height=height)
    db.add(photo)
    db.flush()
    token = secrets.token_urlsafe(32)
    job = RecognitionJob(
        photo_id=photo.id,
        user_id=user_id,
        token_hash=digest(token),
        kind=kind,
        expires_at=utcnow() + timedelta(hours=24),
    )
    db.add(job)
    db.flush()
    return photo, job, token


def job_view(job: RecognitionJob):
    return {
        "id": job.id,
        "status": job.status,
        "kind": job.kind,
        "message": UPLOAD_MESSAGE,
        "created_at": job.created_at.isoformat() + "Z",
    }


@app.get("/api/health/live")
def live():
    return {"status": "ok", "version": "0.2.0", "recognition_enabled": False}


@app.get("/api/health/ready")
def ready(db: DB):
    try:
        db.execute(select(Counter).limit(1))  # Requires migrations, not just a reachable DB.
        if get_settings().redis_url:
            redis_client().ping()
    except Exception:
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return {"status": "ready", "recognition_enabled": False}


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
    try:
        data = RegisterData(
            name=name, student_id=student_id, username=username, password=password, consent=consent
        )
    except ValidationError as exc:
        raise HTTPException(422, "请检查姓名、学号、账号、密码及照片使用同意项") from exc
    key, width, height = save_image(photo)
    try:
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
    if not valid or user is None:
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
    return {"items": [photo_view(p) for p in pictures]}


@app.post("/api/me/photos", status_code=201, dependencies=Unsafe)
def upload_standard(
    request: Request, user: Authenticated, db: DB, photo: Annotated[UploadFile, File()]
):
    limit(request, "standard-upload", 20)
    key, width, height = save_image(photo)
    try:
        # Uploads are not active templates until model validation in iteration three.
        picture, job, token = new_photo_job(db, key, width, height, user.id, "enrollment")
        db.commit()
    except Exception:
        db.rollback()
        remove_image(key)
        raise
    return {"photo": photo_view(picture), "job": {**job_view(job), "token": token}}


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
    photo = db.get(Photo, photo_id)
    if not photo or photo.user_id != user.id:
        raise HTTPException(404, "照片不存在")
    key = photo.storage_key
    db.execute(delete(RecognitionJob).where(RecognitionJob.photo_id == photo.id))
    db.delete(photo)
    db.commit()
    remove_image(key)


@app.post("/api/uploads", status_code=201, dependencies=Unsafe)
def upload(request: Request, db: DB, photo: Annotated[UploadFile, File()]):
    limit(request, "anonymous-upload", 60)
    key, width, height = save_image(photo)
    try:
        _, job, token = new_photo_job(db, key, width, height, None, "capture")
        db.commit()
    except Exception:
        db.rollback()
        remove_image(key)
        raise
    return {**job_view(job), "token": token}


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
            {"id": r.id, "event_id": r.event_id, "checked_at": r.checked_at.isoformat() + "Z"}
            for r in records
        ]
    }


@app.exception_handler(SQLAlchemyError)
async def database_error(_request, _exc):
    return JSONResponse(status_code=503, content={"detail": "数据服务暂时不可用，请稍后重试"})
