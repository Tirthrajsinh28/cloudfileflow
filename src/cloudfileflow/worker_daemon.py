import logging
import signal
from collections.abc import Callable
from threading import Event
from types import FrameType
from typing import Protocol

from cloudfileflow.config import Settings
from cloudfileflow.database import create_database
from cloudfileflow.migrations import upgrade_database, verify_database_revision
from cloudfileflow.observability import configure_json_logging
from cloudfileflow.storage import LocalStorage
from cloudfileflow.worker import FileWorker, WorkerResult

LOGGER = logging.getLogger("cloudfileflow.worker")


class WorkerRunner(Protocol):
    def run_once(self) -> WorkerResult | None: ...


def run_loop(
    worker: WorkerRunner,
    stop: Event,
    poll_seconds: float,
) -> None:
    while not stop.is_set():
        try:
            result = worker.run_once()
        except Exception:
            LOGGER.exception("worker_loop_failed", extra={"event": "worker_loop_failed"})
            result = None
        if result is None:
            stop.wait(poll_seconds)


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
    stop = Event()

    def request_stop(signum: int, frame: FrameType | None) -> None:
        del signum, frame
        stop.set()

    register_signal_handlers(request_stop)
    LOGGER.info("worker_started", extra={"event": "worker_started"})
    run_loop(worker, stop, settings.worker_poll_seconds)
    LOGGER.info("worker_stopped", extra={"event": "worker_stopped"})


def register_signal_handlers(
    handler: Callable[[int, FrameType | None], None],
) -> None:
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)
