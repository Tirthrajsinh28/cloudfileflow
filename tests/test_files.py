from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import UUID

import jwt
from fastapi.testclient import TestClient
from httpx2 import Response
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from cloudfileflow.app import create_app
from cloudfileflow.config import Settings
from cloudfileflow.database import AuditRecord, FileRecord, ProcessingJob, get_session

SECRET = "synthetic-upload-signing-secret-32-characters"
ISSUER = "cloudfileflow-upload-test"
OWNER_ID = UUID("e1111111-1111-1111-1111-111111111111")
OTHER_OWNER_ID = UUID("e2222222-2222-2222-2222-222222222222")


def settings_for(tmp_path: Path, max_file_bytes: int = 1024) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'cloudfileflow.sqlite3'}",
        storage_root=tmp_path / "storage",
        auto_migrate=True,
        jwt_secret=SecretStr(SECRET),
        jwt_issuer=ISSUER,
        max_file_bytes=max_file_bytes,
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
    *,
    content: bytes = b"synthetic content",
    filename: str = "synthetic.txt",
    media_type: str = "text/plain",
    key: str = "upload-key-001",
    owner_id: UUID = OWNER_ID,
) -> Response:
    return client.post(
        "/api/v1/files",
        headers={**bearer(owner_id), "Idempotency-Key": key},
        files={"upload": (filename, content, media_type)},
    )


def counts(factory: sessionmaker[Session]) -> tuple[int, int, int]:
    with factory() as session:
        return (
            session.scalar(select(func.count()).select_from(FileRecord)) or 0,
            session.scalar(select(func.count()).select_from(ProcessingJob)) or 0,
            session.scalar(select(func.count()).select_from(AuditRecord)) or 0,
        )


def test_upload_streams_to_generated_quarantine_and_commits_records(tmp_path: Path) -> None:
    application = create_app(settings_for(tmp_path))
    with TestClient(application) as client:
        response = upload(
            client,
            content=b"synthetic file contents",
            filename="../../candidate-records.txt",
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["display_name"] == "candidate-records.txt"
    assert payload["declared_media_type"] == "text/plain"
    assert payload["byte_size"] == 23
    assert payload["state"] == "QUARANTINED"
    assert response.headers["location"] == f"/api/v1/files/{payload['id']}"
    assert counts(application.state.session_factory) == (1, 1, 1)

    quarantine_files = [
        path for path in (tmp_path / "storage" / "quarantine").glob("*") if path.is_file()
    ]
    assert len(quarantine_files) == 1
    assert quarantine_files[0].name != "candidate-records.txt"
    assert quarantine_files[0].read_bytes() == b"synthetic file contents"


def test_idempotent_retry_returns_original_without_duplicate_storage(tmp_path: Path) -> None:
    application = create_app(settings_for(tmp_path))
    with TestClient(application) as client:
        first = upload(client, content=b"first payload", key="stable-upload-key")
        second = upload(client, content=b"different payload", key="stable-upload-key")

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["sha256"] == first.json()["sha256"]
    assert counts(application.state.session_factory) == (1, 1, 1)
    quarantine_files = [
        path for path in (tmp_path / "storage" / "quarantine").glob("*") if path.is_file()
    ]
    assert len(quarantine_files) == 1


def test_rejects_disallowed_empty_oversize_and_bad_idempotency(tmp_path: Path) -> None:
    application = create_app(settings_for(tmp_path, max_file_bytes=16))
    with TestClient(application) as client:
        responses = [
            upload(client, media_type="application/zip", key="disallow-001"),
            upload(client, content=b"", key="empty-file-001"),
            upload(client, content=b"x" * 17, key="oversize-file-001"),
            upload(client, key="../bad"),
        ]

    assert [response.status_code for response in responses] == [415, 400, 413, 400]
    assert counts(application.state.session_factory) == (0, 0, 0)
    assert not [path for path in (tmp_path / "storage" / "quarantine").glob("*") if path.is_file()]
    assert not list((tmp_path / "storage" / "quarantine" / ".tmp").glob("*"))


def test_metadata_is_owner_scoped_and_upload_requires_authentication(tmp_path: Path) -> None:
    application = create_app(settings_for(tmp_path))
    with TestClient(application) as client:
        created = upload(client)
        file_id = created.json()["id"]
        owner_response = client.get(f"/api/v1/files/{file_id}", headers=bearer())
        other_response = client.get(
            f"/api/v1/files/{file_id}",
            headers=bearer(OTHER_OWNER_ID),
        )
        anonymous_upload = client.post(
            "/api/v1/files",
            headers={"Idempotency-Key": "anonymous-upload"},
            files={"upload": ("synthetic.txt", b"data", "text/plain")},
        )

    assert owner_response.status_code == 200
    assert other_response.status_code == 404
    assert anonymous_upload.status_code == 401


def test_unique_race_returns_winner_and_cleans_losing_object(tmp_path: Path) -> None:
    application = create_app(settings_for(tmp_path))
    winner = FileRecord(
        id=UUID("e3333333-3333-3333-3333-333333333333"),
        owner_id=OWNER_ID,
        idempotency_key="concurrent-upload",
        display_name="winner.txt",
        storage_key="winner-storage-key",
        declared_media_type="text/plain",
        byte_size=6,
        sha256="0" * 64,
        state="QUARANTINED",
        created_at=datetime.now(UTC),
    )

    class ConflictSession:
        scalar_calls = 0

        def scalar(self, statement: object) -> FileRecord | None:
            del statement
            self.scalar_calls += 1
            return None if self.scalar_calls == 1 else winner

        def add(self, record: object) -> None:
            del record

        def flush(self) -> None:
            raise IntegrityError("insert", {}, RuntimeError("synthetic unique race"))

        def rollback(self) -> None:
            pass

    conflict_session = ConflictSession()

    def conflict_dependency() -> Session:
        return cast(Session, conflict_session)

    application.dependency_overrides[get_session] = conflict_dependency
    with TestClient(application) as client:
        response = upload(
            client,
            content=b"losing payload",
            key="concurrent-upload",
        )

    assert response.status_code == 200
    assert response.json()["id"] == str(winner.id)
    assert response.json()["display_name"] == "winner.txt"
    assert conflict_session.scalar_calls == 2
    assert not [path for path in (tmp_path / "storage" / "quarantine").glob("*") if path.is_file()]
