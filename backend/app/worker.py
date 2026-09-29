"""One prefork CPU worker, with readiness only after verified models load."""

import json
import os
from pathlib import Path

from celery import Celery
from celery.signals import heartbeat_sent, worker_process_init, worker_process_shutdown

from app.config import get_settings
from app.db import get_engine
from app.jobs import WORKER_KEY, process_job
from app.limits import redis_client
from app.model_assets import MODEL_VERSION

celery = Celery("attendance", broker=get_settings().redis_url or "redis://localhost:6379/0")
celery.conf.update(
    task_default_queue="attendance",
    task_serializer="json",
    accept_content=["json"],
    task_ignore_result=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    broker_connection_retry_on_startup=True,
    broker_connection_timeout=3,
    broker_transport_options={
        "visibility_timeout": 90,
        "global_keyprefix": "attendance:celery:",
        "socket_connect_timeout": 3,
        "socket_timeout": 3,
    },
    task_soft_time_limit=30,
    task_time_limit=40,
)
READY_FILE = Path("/tmp/attendance-worker-ready.json")


@worker_process_init.connect
def load_model(**_):
    from app.vision import get_face_engine

    get_engine.cache_clear()
    redis_client.cache_clear()
    get_face_engine()
    temporary = READY_FILE.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps({"pid": os.getpid(), "model_version": MODEL_VERSION}))
    temporary.replace(READY_FILE)


@heartbeat_sent.connect
def ready_heartbeat(**_):
    try:
        info = json.loads(READY_FILE.read_text())
        os.kill(info["pid"], 0)
        redis_client().set(WORKER_KEY, json.dumps(info), ex=15)
    except (OSError, ValueError):
        pass
    except Exception:
        pass  # Redis failure causes TTL expiry and admission to fail closed.


@worker_process_shutdown.connect
def remove_readiness(**_):
    try:
        if json.loads(READY_FILE.read_text())["pid"] == os.getpid():
            READY_FILE.unlink(missing_ok=True)
    except (OSError, ValueError):
        pass


@celery.task(name="attendance.recognize")
def recognize(job_id: str):
    process_job(job_id)
