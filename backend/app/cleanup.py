"""Remove expired anonymous uploads; standard photos remain owner-managed."""

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db import get_engine
from app.jobs import PENDING, finish, queue_lock
from app.models import Photo, RecognitionJob, UserSession, utcnow
from app.storage import remove_image


def cleanup() -> int:
    keys = []
    with Session(get_engine()) as db:
        queue_lock(db)
        jobs = db.scalars(
            select(RecognitionJob).where(
                RecognitionJob.kind == "capture", RecognitionJob.expires_at <= utcnow()
            )
        ).all()
        for job in jobs:
            if job.status in PENDING:
                finish(db, job, "queue_timeout", "failed")
            photo = db.get(Photo, job.photo_id) if job.photo_id else None
            db.delete(job)
            db.flush()
            if photo:
                keys.append(photo.storage_key)
                db.delete(photo)
        db.execute(delete(UserSession).where(UserSession.expires_at <= utcnow()))
        # Enrollment results can expire without deleting owner-managed photos/templates.
        db.execute(
            delete(RecognitionJob).where(
                RecognitionJob.kind == "enrollment",
                RecognitionJob.expires_at <= utcnow(),
                RecognitionJob.status.not_in(PENDING),
            )
        )
        db.commit()
    for key in keys:
        remove_image(key)
    return len(keys)


if __name__ == "__main__":
    print(f"Removed {cleanup()} expired uploads")
