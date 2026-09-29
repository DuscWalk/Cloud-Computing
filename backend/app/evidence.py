"""Create a private, redacted HTML snapshot without identities, tokens or embeddings."""

import html
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_engine
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


def table(headers, rows):
    def cells(values, tag):
        return (
            "<tr>"
            + "".join(
                f"<{tag}>{html.escape(str(v) if v is not None else '—')}</{tag}>" for v in values
            )
            + "</tr>"
        )

    return "<table>" + cells(headers, "th") + "".join(cells(row, "td") for row in rows) + "</table>"


def snapshot(output: Path):
    sections = []
    with Session(get_engine()) as db:
        for model in [User, Photo, RecognitionJob, UserSession, AttendanceEvent, AttendanceRecord]:
            count = db.scalar(select(func.count()).select_from(model))
            sections.append(f"<h2>{model.__tablename__}: {count} rows</h2>")
        sections.append("<h2>face_templates</h2>")
        sections.append(
            table(
                [
                    "photo_id",
                    "user_id",
                    "status",
                    "purpose",
                    "image size",
                    "feature dim",
                    "revision",
                    "model",
                ],
                (
                    [
                        p.id[:8],
                        (p.user_id or "")[:8],
                        p.status,
                        p.purpose,
                        f"{p.width}x{p.height}",
                        len(p.embedding) if p.embedding else 0,
                        p.revision,
                        p.model_version,
                    ]
                    for p in db.scalars(select(Photo))
                ),
            )
        )
        sections.append("<h2>recognition_jobs (latest 100)</h2>")
        sections.append(
            table(
                [
                    "job_id",
                    "kind",
                    "status",
                    "result",
                    "faces",
                    "feature dim",
                    "inference ms",
                    "model",
                ],
                (
                    [
                        j.id[:8],
                        j.kind,
                        j.status,
                        j.result_code,
                        j.detected_faces,
                        j.feature_dim,
                        round(j.inference_ms, 2) if j.inference_ms is not None else None,
                        j.model_version,
                    ]
                    for j in db.scalars(
                        select(RecognitionJob).order_by(RecognitionJob.created_at.desc()).limit(100)
                    )
                ),
            )
        )
        sections.append("<h2>attendance_records</h2>")
        sections.append(
            table(
                [
                    "record_id",
                    "event_id",
                    "user_id",
                    "checked_at UTC",
                    "similarity",
                    "template revision",
                    "model",
                ],
                (
                    [
                        r.id[:8],
                        r.event_id[:8],
                        r.user_id[:8],
                        r.checked_at,
                        round(r.similarity, 4) if r.similarity is not None else None,
                        r.template_revision,
                        r.model_version,
                    ]
                    for r in db.scalars(select(AttendanceRecord))
                ),
            )
        )
        pending = db.get(Counter, "recognition_pending")
        sections.append(
            f"<p>recognition_pending: {pending.value if pending else 'not migrated'}</p>"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "<!doctype html><html lang='en'><meta charset='utf-8'>"
        "<title>Database evidence</title><style>body{font:16px system-ui;"
        "margin:32px}td,th{padding:12px;border:1px solid #ccc}"
        "table{border-collapse:collapse}</style><h1>Database snapshot</h1>"
        f"<p>UTC: {utcnow().isoformat()}</p>" + "".join(sections),
        encoding="utf-8",
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("../artifacts/database.html"))
    args = parser.parse_args()
    snapshot(args.output)
    print(f"Snapshot: {args.output.resolve()}")
