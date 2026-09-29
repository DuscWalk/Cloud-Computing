"""Remove expired anonymous uploads; standard photos remain owner-managed."""

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db import get_engine
from app.models import Photo, RecognitionJob, UserSession, utcnow
from app.storage import remove_image


def cleanup() -> int:
    keys = []
    with Session(get_engine()) as db:
        jobs = db.scalars(
            select(RecognitionJob).where(
                RecognitionJob.kind == "capture", RecognitionJob.expires_at <= utcnow()
            )
        ).all()
        for job in jobs:
            photo = db.get(Photo, job.photo_id) if job.photo_id else None
            db.delete(job)
            db.flush()
            if photo:
                keys.append(photo.storage_key)
                db.delete(photo)
        db.execute(delete(UserSession).where(UserSession.expires_at <= utcnow()))
        db.commit()
    for key in keys:
        remove_image(key)
    return len(keys)


if __name__ == "__main__":
    print(f"Removed {cleanup()} expired uploads")
