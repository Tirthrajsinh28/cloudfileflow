"""Create file, processing job, and audit tables.

Revision ID: 20260704_01
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260704_01"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "files",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("storage_key", sa.String(length=80), nullable=False),
        sa.Column("declared_media_type", sa.String(length=100), nullable=False),
        sa.Column("detected_media_type", sa.String(length=100), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("byte_size > 0", name="ck_file_nonempty"),
        sa.CheckConstraint(
            "state != 'READY' or detected_media_type is not null",
            name="ck_file_ready_type",
        ),
        sa.CheckConstraint(
            "state in ('QUARANTINED', 'READY', 'REJECTED')",
            name="ck_file_state",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_id",
            "idempotency_key",
            name="uq_file_owner_idempotency",
        ),
        sa.UniqueConstraint("storage_key"),
    )
    op.create_index("ix_files_owner_id", "files", ["owner_id"], unique=False)
    op.create_table(
        "processing_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("attempt_count >= 0", name="ck_job_attempts"),
        sa.CheckConstraint(
            "(state = 'PROCESSING' and claimed_at is not null) or "
            "(state != 'PROCESSING' and claimed_at is null)",
            name="ck_job_claim_state",
        ),
        sa.CheckConstraint(
            "state in ('PENDING', 'PROCESSING', 'COMPLETED', 'DEAD_LETTER')",
            name="ck_job_state",
        ),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("file_id"),
    )
    op.create_table(
        "audit_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=60), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_audit_records_file_id",
        "audit_records",
        ["file_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_audit_records_file_id", table_name="audit_records")
    op.drop_table("audit_records")
    op.drop_table("processing_jobs")
    op.drop_index("ix_files_owner_id", table_name="files")
    op.drop_table("files")
