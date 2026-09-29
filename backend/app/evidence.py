"""Create a private, redacted HTML database snapshot for iteration-two evidence."""

import html
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_engine
from app.models import AttendanceRecord, Photo, RecognitionJob, User, UserSession, utcnow


def snapshot(output: Path):
    sections = []
    with Session(get_engine()) as db:
        for model in [User, Photo, RecognitionJob, UserSession, AttendanceRecord]:
            count = db.scalar(select(func.count()).select_from(model))
            sections.append(f"<h2>{model.__tablename__}: {count} rows</h2>")
        sections.append(
            "<h2>face_templates</h2><table><tr><th>photo_id</th>"
            "<th>status</th><th>purpose</th><th>dimensions</th></tr>"
        )
        for photo in db.scalars(select(Photo)):
            values = [photo.id[:8], photo.status, photo.purpose, f"{photo.width}x{photo.height}"]
            sections.append(
                "<tr>" + "".join(f"<td>{html.escape(v)}</td>" for v in values) + "</tr>"
            )
        sections.append("</table>")
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
