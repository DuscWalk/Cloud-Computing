"""Database outbox dispatcher: recover crashes and publish pending jobs to Celery."""

import logging
import time
from datetime import timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.db import get_engine
from app.jobs import recover_jobs
from app.models import RecognitionJob, utcnow
from app.worker import recognize

log = logging.getLogger(__name__)


def dispatch_once() -> int:
    recover_jobs()
    now = utcnow()
    with Session(get_engine()) as db:
        rows = db.execute(
            select(RecognitionJob.id, RecognitionJob.deadline_at)
            .where(
                RecognitionJob.status == "queued",
                RecognitionJob.deadline_at > now,
                or_(
                    RecognitionJob.dispatched_at.is_(None),
                    RecognitionJob.dispatched_at < now - timedelta(seconds=30),
                ),
            )
            .order_by(RecognitionJob.created_at)
            .limit(32)
        ).all()
    sent = 0
    for job_id, deadline in rows:
        recognize.apply_async(
            args=[job_id],
            task_id=job_id,
            retry=False,
            expires=max(1, int((deadline - utcnow()).total_seconds())),
        )
        with Session(get_engine()) as db:
            db.execute(
                update(RecognitionJob)
                .where(RecognitionJob.id == job_id)
                .values(dispatched_at=utcnow())
            )
            db.commit()
        sent += 1
    return sent


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    while True:
        try:
            sent = dispatch_once()
            if sent:
                log.info("Published %s recognition jobs", sent)
        except Exception as exc:
            log.warning("Dispatcher will retry after %s", type(exc).__name__)
        time.sleep(2)
