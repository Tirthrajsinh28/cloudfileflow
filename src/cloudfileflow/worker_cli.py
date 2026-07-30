import json

from cloudfileflow.config import Settings
from cloudfileflow.database import create_database
from cloudfileflow.migrations import upgrade_database, verify_database_revision
from cloudfileflow.observability import configure_json_logging
from cloudfileflow.storage import LocalStorage
from cloudfileflow.worker import FileWorker


def main() -> None:
    configure_json_logging()
    settings = Settings()  # type: ignore[call-arg]
    settings.storage_root.parent.mkdir(parents=True, exist_ok=True)
    if settings.auto_migrate:
        upgrade_database(settings.database_url)
    engine, factory = create_database(settings.database_url)
    verify_database_revision(engine, settings.database_url)
    worker = FileWorker(
        factory,
        LocalStorage(settings.storage_root),
        max_attempts=settings.worker_max_attempts,
        retry_base_seconds=settings.worker_retry_base_seconds,
        claim_timeout_seconds=settings.worker_claim_timeout_seconds,
    )
    result = worker.run_once()
    payload = (
        {"processed": False}
        if result is None
        else {
            "processed": True,
            "jobId": str(result.job_id),
            "fileId": str(result.file_id),
            "state": result.state,
        }
    )
    print(json.dumps(payload, separators=(",", ":")))
