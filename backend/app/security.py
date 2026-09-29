import hashlib
import secrets
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import Depends, HTTPException, Request, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import User, UserSession, utcnow

SESSION_COOKIE = "attendance_session"
CSRF_COOKIE = "attendance_csrf"
hasher = PasswordHasher()
DUMMY_HASH = hasher.hash("a-placeholder-password-for-equal-work")


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def serializer():
    return URLSafeTimedSerializer(get_settings().secret_key, salt="attendance-csrf-v1")


def issue_csrf(response: Response) -> str:
    token = serializer().dumps(secrets.token_urlsafe(24))
    response.set_cookie(
        CSRF_COOKIE,
        token,
        httponly=True,
        secure=get_settings().cookie_secure,
        samesite="lax",
        max_age=86400,
        path="/api",
    )
    return token


def require_csrf(request: Request):
    cookie = request.cookies.get(CSRF_COOKIE, "")
    header = request.headers.get("X-CSRF-Token", "")
    if not cookie or not secrets.compare_digest(cookie, header):
        raise HTTPException(403, "请求校验失败，请刷新页面重试")
    try:
        serializer().loads(cookie, max_age=86400)
    except (BadSignature, SignatureExpired) as exc:
        raise HTTPException(403, "页面已过期，请刷新后重试") from exc


def verify_password(password: str, hashed: str) -> bool:
    try:
        return hasher.verify(hashed, password)
    except VerificationError:
        return False


def optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    session = db.get(UserSession, digest(token))
    if not session or session.expires_at <= utcnow():
        return None
    return db.get(User, session.user_id)


def current_user(user: User | None = Depends(optional_user)) -> User:
    if user is None:
        raise HTTPException(401, "请先登录")
    return user


def create_session(response: Response, db: Session, user: User) -> None:
    token = secrets.token_urlsafe(32)
    ttl = get_settings().session_hours * 3600
    db.add(
        UserSession(
            token_hash=digest(token), user_id=user.id, expires_at=utcnow() + timedelta(seconds=ttl)
        )
    )
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        secure=get_settings().cookie_secure,
        samesite="lax",
        max_age=ttl,
        path="/api",
    )
