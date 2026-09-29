"""Explicit local administrator provisioning, never an unauthenticated HTTP route."""

import argparse
import getpass
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_engine
from app.jobs import queue_lock
from app.models import Counter, User
from app.schemas import RegisterData
from app.security import hasher


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["promote", "create-admin"])
    parser.add_argument("username")
    parser.add_argument("--name", default="课程管理员")
    parser.add_argument("--student-id")
    parser.add_argument("--password-stdin", action="store_true")
    args = parser.parse_args()
    password = None
    if args.action == "create-admin":
        password = (
            sys.stdin.readline().rstrip("\r\n")
            if args.password_stdin
            else getpass.getpass("管理员密码: ")
        )
        data = RegisterData(
            username=args.username,
            name=args.name,
            student_id=args.student_id or ("admin_" + args.username)[:32],
            password=password,
            consent=True,
        )
    with Session(get_engine()) as db:
        queue_lock(db)
        user = db.scalar(select(User).where(User.username == args.username.lower()))
        if args.action == "promote":
            if not user or user.status != "active":
                raise SystemExit("需要已注册且启用的账号")
            user.role = "admin"
        else:
            if user:
                raise SystemExit("账号已存在；如需授权请使用 promote")
            counter = db.get(Counter, "registered_users")
            if counter.value >= get_settings().max_users:
                raise SystemExit("人员库已满")
            counter.value += 1
            db.add(
                User(
                    username=data.username.lower(),
                    name=data.name,
                    student_id=data.student_id,
                    password_hash=hasher.hash(password),
                    role="admin",
                )
            )
        db.commit()
    print("管理员授权已完成；未录入人脸的管理员也可管理活动。")


if __name__ == "__main__":
    main()
