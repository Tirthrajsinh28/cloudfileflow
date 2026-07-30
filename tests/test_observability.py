import json
import logging
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient
from pydantic import SecretStr

from cloudfileflow.app import create_app
from cloudfileflow.config import Settings
from cloudfileflow.observability import JsonFormatter

SECRET = "synthetic-observability-secret-32-characters"


def settings_for(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'observability.sqlite3'}",
        storage_root=tmp_path / "storage",
        auto_migrate=True,
        jwt_secret=SecretStr(SECRET),
        operator_owner_id=UUID("e1111111-1111-1111-1111-111111111111"),
    )


def test_request_id_is_bounded_and_propagated(tmp_path: Path) -> None:
    with TestClient(create_app(settings_for(tmp_path))) as client:
        retained = client.get("/health", headers={"X-Request-ID": "demo-request_01"})
        replaced = client.get("/health", headers={"X-Request-ID": "../unsafe request"})

    assert retained.headers["x-request-id"] == "demo-request_01"
    assert replaced.headers["x-request-id"] != "../unsafe request"
    assert len(replaced.headers["x-request-id"]) == 36


def test_json_formatter_includes_bounded_fields_without_message_payload() -> None:
    record = logging.LogRecord(
        name="cloudfileflow.worker",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="job_finished",
        args=(),
        exc_info=None,
    )
    record.event = "job_finished"
    record.job_id = "job-1"
    record.file_id = "file-1"
    record.job_state = "COMPLETED"

    payload = json.loads(JsonFormatter().format(record))

    assert payload["event"] == "job_finished"
    assert payload["job_id"] == "job-1"
    assert payload["file_id"] == "file-1"
    assert payload["job_state"] == "COMPLETED"
    assert "message" not in payload
