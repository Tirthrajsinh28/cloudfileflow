from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx2 import Response
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from cloudfileflow.app import create_app
from cloudfileflow.config import Settings
from cloudfileflow.content import validate_content
from cloudfileflow.database import AuditRecord, FileRecord, ProcessingJob
from cloudfileflow.storage import LocalStorage
from cloudfileflow.worker import FileWorker
from cloudfileflow.worker_cli import main as worker_main

SECRET = "synthetic-worker-signing-secret-32-characters"
ISSUER = "cloudfileflow-worker-test"
OWNER_ID = UUID("e1111111-1111-1111-1111-111111111111")
OTHER_OWNER_ID = UUID("e2222222-2222-2222-2222-222222222222")


def settings_for(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'cloudfileflow.sqlite3'}",
        storage_root=tmp_path / "storage",
        auto_migrate=True,
        jwt_secret=SecretStr(SECRET),
        jwt_issuer=ISSUER,
        max_file_bytes=1024,
        worker_max_attempts=3,
        worker_retry_base_seconds=10,
        worker_claim_timeout_seconds=60,
        operator_owner_id=OWNER_ID,
    )


def bearer(owner_id: UUID = OWNER_ID) -> dict[str, str]:
    encoded = jwt.encode(
        {
            "sub": str(owner_id),
            "iss": ISSUER,
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        SECRET,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {encoded}"}


def upload(
    client: TestClient,
    content: bytes,
    media_type: str,
    *,
    filename: str = "synthetic.txt",
) -> Response:
    return client.post(
        "/api/v1/files",
        headers={**bearer(), "Idempotency-Key": f"worker-{filename}"},
        files={"upload": (filename, content, media_type)},
    )


def worker_for(
    application: FastAPI,
    validator: Callable[[Path, str], str] = validate_content,
) -> FileWorker:
    return FileWorker(
        application.state.session_factory,
        application.state.storage,
        max_attempts=3,
        retry_base_seconds=10,
        claim_timeout_seconds=60,
        validator=validator,
    )


def database_records(
    factory: sessionmaker[Session],
) -> tuple[FileRecord, ProcessingJob, list[AuditRecord]]:
    with factory() as session:
        record = session.scalars(select(FileRecord)).one()
        job = session.scalars(select(ProcessingJob)).one()
        events = list(
            session.scalars(select(AuditRecord).order_by(AuditRecord.occurred_at, AuditRecord.id))
        )
        session.expunge(record)
        session.expunge(job)
        for event in events:
            session.expunge(event)
        return record, job, events


def test_valid_json_is_promoted_audited_and_owner_downloadable(tmp_path: Path) -> None:
    application = create_app(settings_for(tmp_path))
    now = datetime.now(UTC) + timedelta(seconds=1)
    with TestClient(application) as client:
        created = upload(
            client,
            b'{"kind":"synthetic","safe":true}',
            "application/json",
            filename="fixture.json",
        )
        file_id = created.json()["id"]
        result = worker_for(application).run_once(now)
        metadata = client.get(f"/api/v1/files/{file_id}", headers=bearer())
        job_response = client.get(f"/api/v1/files/{file_id}/job", headers=bearer())
        audit_response = client.get(f"/api/v1/files/{file_id}/audit", headers=bearer())
        download = client.get(f"/api/v1/files/{file_id}/content", headers=bearer())
        other_download = client.get(
            f"/api/v1/files/{file_id}/content",
            headers=bearer(OTHER_OWNER_ID),
        )

    assert created.status_code == 201
    assert result is not None and result.state == "COMPLETED"
    assert metadata.status_code == 200
    assert metadata.json()["state"] == "READY"
    assert job_response.json()["state"] == "COMPLETED"
    assert job_response.json()["attempt_count"] == 1
    assert job_response.json()["last_error"] is None
    assert [event["action"] for event in audit_response.json()] == [
        "FILE_QUARANTINED",
        "FILE_READY",
    ]
    assert download.status_code == 200
    assert download.content == b'{"kind":"synthetic","safe":true}'
    assert download.headers["content-type"] == "application/json"
    assert download.headers["cache-control"] == "private, no-store"
    assert download.headers["x-content-type-options"] == "nosniff"
    assert 'filename="fixture.json"' in download.headers["content-disposition"]
    assert other_download.status_code == 404

    record, job, _ = database_records(application.state.session_factory)
    storage: LocalStorage = application.state.storage
    assert job.state == "COMPLETED"
    assert not storage.quarantine_path(record.storage_key).exists()
    assert storage.ready_path(record.storage_key).is_file()


def test_invalid_json_is_rejected_deleted_and_not_downloadable(tmp_path: Path) -> None:
    application = create_app(settings_for(tmp_path))
    with TestClient(application) as client:
        created = upload(client, b'{"broken":', "application/json", filename="broken.json")
        file_id = created.json()["id"]
        result = worker_for(application).run_once()
        metadata = client.get(f"/api/v1/files/{file_id}", headers=bearer())
        job_response = client.get(f"/api/v1/files/{file_id}/job", headers=bearer())
        download = client.get(f"/api/v1/files/{file_id}/content", headers=bearer())

    record, job, events = database_records(application.state.session_factory)
    storage: LocalStorage = application.state.storage
    assert result is not None and result.state == "COMPLETED"
    assert metadata.json()["state"] == "REJECTED"
    assert job_response.json()["last_error"] == "ContentRejectedError"
    assert download.status_code == 409
    assert job.state == "COMPLETED"
    assert [event.action for event in events] == ["FILE_QUARANTINED", "FILE_REJECTED"]
    assert not storage.quarantine_path(record.storage_key).exists()
    assert not storage.ready_path(record.storage_key).exists()


def test_transient_failure_retries_with_backoff_then_dead_letters(tmp_path: Path) -> None:
    application = create_app(settings_for(tmp_path))
    with TestClient(application) as client:
        upload(client, b"synthetic", "text/plain")

    def unavailable_validator(path: Path, media_type: str) -> str:
        del path, media_type
        raise OSError("synthetic adapter outage")

    worker = worker_for(application, unavailable_validator)
    start = datetime.now(UTC) + timedelta(seconds=1)

    first = worker.run_once(start)
    too_early = worker.run_once(start + timedelta(seconds=9))
    second = worker.run_once(start + timedelta(seconds=10))
    third = worker.run_once(start + timedelta(seconds=30))

    record, job, events = database_records(application.state.session_factory)
    storage: LocalStorage = application.state.storage
    assert first is not None and first.state == "PENDING"
    assert too_early is None
    assert second is not None and second.state == "PENDING"
    assert third is not None and third.state == "DEAD_LETTER"
    assert job.state == "DEAD_LETTER"
    assert job.attempt_count == 3
    assert job.last_error == "OSError"
    assert [event.action for event in events] == [
        "FILE_QUARANTINED",
        "JOB_RETRY_SCHEDULED",
        "JOB_RETRY_SCHEDULED",
        "JOB_DEAD_LETTER",
    ]
    assert record.state == "QUARANTINED"
    assert storage.quarantine_path(record.storage_key).is_file()


def test_stale_claim_is_recovered_before_processing(tmp_path: Path) -> None:
    application = create_app(settings_for(tmp_path))
    with TestClient(application) as client:
        upload(client, b"synthetic", "text/plain")

    now = datetime.now(UTC) + timedelta(seconds=1)
    with application.state.session_factory() as session:
        job = session.scalars(select(ProcessingJob)).one()
        job.state = "PROCESSING"
        job.attempt_count = 1
        job.claimed_at = now - timedelta(seconds=61)
        session.commit()

    result = worker_for(application).run_once(now)
    _, job, events = database_records(application.state.session_factory)
    assert result is not None and result.state == "COMPLETED"
    assert job.state == "COMPLETED"
    assert job.attempt_count == 2
    assert [event.action for event in events] == [
        "FILE_QUARANTINED",
        "JOB_STALE_CLAIM_RECOVERED",
        "FILE_READY",
    ]


def test_stale_final_attempt_moves_directly_to_dead_letter(tmp_path: Path) -> None:
    application = create_app(settings_for(tmp_path))
    with TestClient(application) as client:
        upload(client, b"synthetic", "text/plain")

    now = datetime.now(UTC) + timedelta(seconds=1)
    with application.state.session_factory() as session:
        job = session.scalars(select(ProcessingJob)).one()
        job.state = "PROCESSING"
        job.attempt_count = 3
        job.claimed_at = now - timedelta(seconds=61)
        session.commit()

    worker = worker_for(application)
    assert worker.recover_stale_claims(now) == 1
    assert worker.run_once(now) is None
    _, job, events = database_records(application.state.session_factory)
    assert job.state == "DEAD_LETTER"
    assert [event.action for event in events] == [
        "FILE_QUARANTINED",
        "JOB_DEAD_LETTER",
    ]


def test_worker_returns_none_when_no_job_is_due(tmp_path: Path) -> None:
    application = create_app(settings_for(tmp_path))
    assert worker_for(application).run_once() is None


def test_worker_cli_reports_empty_queue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("CLOUDFILEFLOW_DATABASE_URL", f"sqlite:///{tmp_path / 'cli.sqlite3'}")
    monkeypatch.setenv("CLOUDFILEFLOW_STORAGE_ROOT", str(tmp_path / "cli-storage"))
    monkeypatch.setenv("CLOUDFILEFLOW_AUTO_MIGRATE", "true")
    monkeypatch.setenv("CLOUDFILEFLOW_JWT_SECRET", SECRET)
    monkeypatch.setenv("CLOUDFILEFLOW_JWT_ISSUER", ISSUER)

    worker_main()

    assert capsys.readouterr().out == '{"processed":false}\n'


def test_operator_job_view_is_bounded_and_fail_closed(tmp_path: Path) -> None:
    application = create_app(settings_for(tmp_path))
    with TestClient(application) as client:
        upload(client, b"synthetic", "text/plain")

        def unavailable_validator(path: Path, media_type: str) -> str:
            del path, media_type
            raise OSError("sensitive adapter detail")

        worker = worker_for(application, unavailable_validator)
        start = datetime.now(UTC) + timedelta(seconds=1)
        worker.run_once(start)
        worker.run_once(start + timedelta(seconds=10))
        worker.run_once(start + timedelta(seconds=30))

        operator = client.get("/api/v1/operations/jobs", headers=bearer())
        non_operator = client.get(
            "/api/v1/operations/jobs",
            headers=bearer(OTHER_OWNER_ID),
        )
        anonymous = client.get("/api/v1/operations/jobs")

    assert operator.status_code == 200
    payload = operator.json()
    assert payload["counts"] == {
        "pending": 0,
        "processing": 0,
        "completed": 0,
        "dead_letter": 1,
    }
    assert len(payload["dead_letter_jobs"]) == 1
    assert payload["dead_letter_jobs"][0]["attempt_count"] == 3
    assert payload["dead_letter_jobs"][0]["last_error"] == "OSError"
    assert "sensitive adapter detail" not in operator.text
    assert "owner" not in operator.text
    assert non_operator.status_code == 403
    assert anonymous.status_code == 401
