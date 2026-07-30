from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from cloudfileflow.app import create_app
from cloudfileflow.config import Settings
from cloudfileflow.database import (
    FileRecord,
    ProcessingJob,
    create_database,
    ensure_sqlite_parent_directory,
)
from cloudfileflow.migrations import alembic_config, upgrade_database

SECRET = "synthetic-migration-secret-32-characters"


def settings_for(tmp_path: Path, *, auto_migrate: bool = False) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'migration.sqlite3'}",
        storage_root=tmp_path / "storage",
        auto_migrate=auto_migrate,
        jwt_secret=SecretStr(SECRET),
    )


def test_empty_database_requires_upgrade_then_starts_at_head(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    with pytest.raises(RuntimeError, match="alembic upgrade head"):
        create_app(settings)

    upgrade_database(settings.database_url)
    application = create_app(settings)
    with TestClient(application) as client:
        response = client.get("/health")

    assert response.status_code == 200
    engine, _ = create_database(settings.database_url)
    assert set(inspect(engine).get_table_names()) == {
        "alembic_version",
        "audit_records",
        "files",
        "processing_jobs",
    }


def test_sqlite_database_parent_directory_is_created(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'missing' / 'nested' / 'local.sqlite3'}"

    ensure_sqlite_parent_directory(database_url)

    engine, _ = create_database(database_url)
    try:
        with engine.connect() as connection:
            assert connection.exec_driver_sql("select 1").scalar_one() == 1
    finally:
        engine.dispose()


def test_programmatic_migration_uses_explicit_url_when_environment_is_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_database_url = f"sqlite:///{tmp_path / 'environment.sqlite3'}"
    explicit_settings = settings_for(tmp_path / "explicit")
    monkeypatch.setenv("CLOUDFILEFLOW_DATABASE_URL", env_database_url)

    upgrade_database(explicit_settings.database_url)

    application = create_app(explicit_settings)
    with TestClient(application) as client:
        response = client.get("/health")

    assert response.status_code == 200
    explicit_engine, _ = create_database(explicit_settings.database_url)
    env_engine, _ = create_database(env_database_url)
    try:
        assert "alembic_version" in inspect(explicit_engine).get_table_names()
        assert "alembic_version" not in inspect(env_engine).get_table_names()
    finally:
        explicit_engine.dispose()
        env_engine.dispose()


def test_migration_constraints_reject_invalid_file_and_orphan_job(tmp_path: Path) -> None:
    settings = settings_for(tmp_path, auto_migrate=True)
    application = create_app(settings)
    factory = application.state.session_factory
    now = datetime.now(UTC)

    with factory() as session:
        session.add(
            FileRecord(
                owner_id=uuid4(),
                idempotency_key="invalid-byte-size",
                display_name="invalid.txt",
                storage_key=uuid4().hex,
                declared_media_type="text/plain",
                byte_size=0,
                sha256="0" * 64,
                state="QUARANTINED",
                created_at=now,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        session.add(
            ProcessingJob(
                file_id=uuid4(),
                state="PENDING",
                attempt_count=0,
                next_attempt_at=now,
                created_at=now,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_initial_migration_downgrades_to_empty_schema(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    upgrade_database(settings.database_url)

    command.downgrade(alembic_config(settings.database_url), "base")

    engine, factory = create_database(settings.database_url)
    del factory
    remaining = set(inspect(engine).get_table_names())
    assert remaining <= {"alembic_version"}
