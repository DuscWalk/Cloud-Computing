"""Recognition queue, events and results; preserve iteration-two accounts/photos."""

import sqlalchemy as sa
from alembic import op

revision = "fc5722fefb26"
down_revision = "bab7fae7c2ab"
branch_labels = None
depends_on = None

JOB_COLUMNS = [
    sa.Column("event_id", sa.String(32)),
    sa.Column("idempotency_key", sa.String(64)),
    sa.Column("payload_hash", sa.String(64)),
    sa.Column("result_code", sa.String(40)),
    sa.Column("result", sa.JSON()),
    sa.Column("model_version", sa.String(100)),
    sa.Column("detected_faces", sa.Integer()),
    sa.Column("feature_dim", sa.Integer()),
    sa.Column("inference_ms", sa.Float()),
    sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
    sa.Column("slot_reserved", sa.Boolean(), server_default="0", nullable=False),
    sa.Column("dispatched_at", sa.DateTime()),
    sa.Column("started_at", sa.DateTime()),
    sa.Column("completed_at", sa.DateTime()),
    sa.Column("lease_token", sa.String(32)),
    sa.Column("lease_expires_at", sa.DateTime()),
    sa.Column("deadline_at", sa.DateTime()),
]


def upgrade():
    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column("status", sa.String(16), server_default="active", nullable=False)
        )
    with op.batch_alter_table("attendance_events") as batch:
        batch.add_column(
            sa.Column("status", sa.String(16), server_default="active", nullable=False)
        )
        batch.add_column(sa.Column("created_by", sa.String(32)))
        batch.create_foreign_key("fk_event_creator", "users", ["created_by"], ["id"])
    with op.batch_alter_table("attendance_records") as batch:
        batch.add_column(sa.Column("similarity", sa.Float()))
        batch.add_column(sa.Column("model_version", sa.String(100)))
        batch.add_column(sa.Column("source_job_id", sa.String(32)))
        batch.add_column(sa.Column("template_id", sa.String(32)))
    with op.batch_alter_table("face_templates") as batch:
        batch.add_column(sa.Column("reason", sa.String(64)))
    with op.batch_alter_table("recognition_jobs") as batch:
        for column in JOB_COLUMNS:
            batch.add_column(column)
        batch.create_index("ix_recognition_jobs_deadline_at", ["deadline_at"])
        batch.create_index("ix_recognition_jobs_event_id", ["event_id"])
        batch.create_unique_constraint("uq_job_idempotency", ["idempotency_key"])
        batch.create_foreign_key("fk_job_event", "attendance_events", ["event_id"], ["id"])
    op.bulk_insert(
        sa.table("system_counters", sa.column("name"), sa.column("value")),
        [{"name": "recognition_pending", "value": 0}],
    )
    op.execute(
        "UPDATE recognition_jobs SET status='failed', result_code='upgrade_required' "
        "WHERE status='uploaded'"
    )


def downgrade():
    op.execute("DELETE FROM system_counters WHERE name='recognition_pending'")
    with op.batch_alter_table("recognition_jobs") as batch:
        batch.drop_constraint("fk_job_event", type_="foreignkey")
        batch.drop_constraint("uq_job_idempotency", type_="unique")
        batch.drop_index("ix_recognition_jobs_event_id")
        batch.drop_index("ix_recognition_jobs_deadline_at")
        for column in reversed(JOB_COLUMNS):
            batch.drop_column(column.name)
    with op.batch_alter_table("face_templates") as batch:
        batch.drop_column("reason")
    with op.batch_alter_table("attendance_records") as batch:
        for name in ("template_id", "source_job_id", "model_version", "similarity"):
            batch.drop_column(name)
    with op.batch_alter_table("attendance_events") as batch:
        batch.drop_constraint("fk_event_creator", type_="foreignkey")
        batch.drop_column("created_by")
        batch.drop_column("status")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("status")
