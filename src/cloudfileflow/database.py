from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import Request
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy import Uuid as SqlUuid
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class FileRecord(Base):
    __tablename__ = "files"
    __table_args__ = (
        UniqueConstraint("owner_id", "idempotency_key", name="uq_file_owner_idempotency"),
        CheckConstraint("byte_size > 0", name="ck_file_nonempty"),
        CheckConstraint(
            "state in ('QUARANTINED', 'READY', 'REJECTED')",
            name="ck_file_state",
        ),
        CheckConstraint(
            "state != 'READY' or detected_media_type is not null",
            name="ck_file_ready_type",
        ),
    )

    id: Mapped[UUID] = mapped_column(SqlUuid, primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(SqlUuid, nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    declared_media_type: Mapped[str] = mapped_column(String(100), nullable=False)
    detected_media_type: Mapped[str | None] = mapped_column(String(100))
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"
    __table_args__ = (
        CheckConstraint(
            "state in ('PENDING', 'PROCESSING', 'COMPLETED', 'DEAD_LETTER')",
            name="ck_job_state",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_job_attempts"),
        CheckConstraint(
            "(state = 'PROCESSING' and claimed_at is not null) or "
            "(state != 'PROCESSING' and claimed_at is null)",
            name="ck_job_claim_state",
        ),
    )

    id: Mapped[UUID] = mapped_column(SqlUuid, primary_key=True, default=uuid4)
    file_id: Mapped[UUID] = mapped_column(
        SqlUuid,
        ForeignKey("files.id"),
        nullable=False,
        unique=True,
    )
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


class AuditRecord(Base):
    __tablename__ = "audit_records"

    id: Mapped[UUID] = mapped_column(SqlUuid, primary_key=True, default=uuid4)
    file_id: Mapped[UUID] = mapped_column(
        SqlUuid,
        ForeignKey("files.id"),
        nullable=False,
        index=True,
    )
    actor_id: Mapped[UUID] = mapped_column(SqlUuid, nullable=False)
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


SYSTEM_ACTOR_ID = UUID(int=0)


def create_database(database_url: str) -> tuple[Engine, sessionmaker[Session]]:
    ensure_sqlite_parent_directory(database_url)
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, connect_args=connect_args)
    if database_url.startswith("sqlite"):
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    return engine, sessionmaker(engine, expire_on_commit=False)


def ensure_sqlite_parent_directory(database_url: str) -> None:
    url = make_url(database_url)
    if not url.drivername.startswith("sqlite"):
        return
    if url.database is None or url.database in {"", ":memory:"}:
        return
    if url.database.startswith("file:"):
        return

    parent = Path(url.database).expanduser().parent
    if str(parent) not in {"", "."}:
        parent.mkdir(parents=True, exist_ok=True)


def _enable_sqlite_foreign_keys(dbapi_connection: object, connection_record: object) -> None:
    del connection_record
    cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


def get_session(request: Request) -> Iterator[Session]:
    factory: sessionmaker[Session] = request.app.state.session_factory
    with factory() as session:
        yield session
