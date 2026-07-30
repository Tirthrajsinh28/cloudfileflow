import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from cloudfileflow.content import ContentRejectedError, validate_content
from cloudfileflow.database import (
    SYSTEM_ACTOR_ID,
    AuditRecord,
    FileRecord,
    ProcessingJob,
    utc_now,
)
from cloudfileflow.storage import LocalStorage

Validator = Callable[[Path, str], str]
LOGGER = logging.getLogger("cloudfileflow.worker")


@dataclass(frozen=True)
class WorkerResult:
    job_id: UUID
    file_id: UUID
    state: str


class FileWorker:
    def __init__(
        self,
        factory: sessionmaker[Session],
        storage: LocalStorage,
        *,
        max_attempts: int,
        retry_base_seconds: int,
        claim_timeout_seconds: int,
        validator: Validator = validate_content,
    ) -> None:
        self.factory = factory
        self.storage = storage
        self.max_attempts = max_attempts
        self.retry_base_seconds = retry_base_seconds
        self.claim_timeout_seconds = claim_timeout_seconds
        self.validator = validator

    def run_once(self, now: datetime | None = None) -> WorkerResult | None:
        current_time = now or utc_now()
        recovered = self.recover_stale_claims(current_time)
        claimed = self._claim_next(current_time)
        if claimed is None:
            return None
        job_id, file_id = claimed
        processing_time = current_time + timedelta(microseconds=1) if recovered else current_time
        try:
            result = self._process(job_id, file_id, processing_time)
        except Exception as error:
            result = self._record_failure(job_id, file_id, error, processing_time)
        LOGGER.info(
            "job_finished",
            extra={
                "event": "job_finished",
                "job_id": str(result.job_id),
                "file_id": str(result.file_id),
                "job_state": result.state,
            },
        )
        return result

    def recover_stale_claims(self, now: datetime | None = None) -> int:
        current_time = now or utc_now()
        cutoff = current_time - timedelta(seconds=self.claim_timeout_seconds)
        recovered = 0
        with self.factory() as session:
            candidates = session.execute(
                select(
                    ProcessingJob.id,
                    ProcessingJob.file_id,
                    ProcessingJob.attempt_count,
                ).where(
                    ProcessingJob.state == "PROCESSING",
                    ProcessingJob.claimed_at <= cutoff,
                )
            ).all()
            for job_id, file_id, attempt_count in candidates:
                terminal = attempt_count >= self.max_attempts
                result = cast(
                    CursorResult[Any],
                    session.execute(
                        update(ProcessingJob)
                        .where(
                            ProcessingJob.id == job_id,
                            ProcessingJob.state == "PROCESSING",
                            ProcessingJob.claimed_at <= cutoff,
                        )
                        .values(
                            state="DEAD_LETTER" if terminal else "PENDING",
                            claimed_at=None,
                            next_attempt_at=current_time,
                            last_error="StaleClaimRecovered",
                        )
                    ),
                )
                if result.rowcount == 1:
                    recovered += 1
                    session.add(
                        AuditRecord(
                            file_id=file_id,
                            actor_id=SYSTEM_ACTOR_ID,
                            action=("JOB_DEAD_LETTER" if terminal else "JOB_STALE_CLAIM_RECOVERED"),
                            occurred_at=current_time,
                        )
                    )
            session.commit()
        return recovered

    def _claim_next(self, now: datetime) -> tuple[UUID, UUID] | None:
        while True:
            with self.factory() as session:
                candidate = session.execute(
                    select(ProcessingJob.id, ProcessingJob.file_id)
                    .where(
                        ProcessingJob.state == "PENDING",
                        ProcessingJob.next_attempt_at <= now,
                        ProcessingJob.attempt_count < self.max_attempts,
                    )
                    .order_by(ProcessingJob.next_attempt_at, ProcessingJob.id)
                    .limit(1)
                ).one_or_none()
                if candidate is None:
                    return None
                job_id, file_id = candidate
                result = cast(
                    CursorResult[Any],
                    session.execute(
                        update(ProcessingJob)
                        .where(
                            ProcessingJob.id == job_id,
                            ProcessingJob.state == "PENDING",
                            ProcessingJob.next_attempt_at <= now,
                        )
                        .values(
                            state="PROCESSING",
                            claimed_at=now,
                            attempt_count=ProcessingJob.attempt_count + 1,
                        )
                    ),
                )
                session.commit()
                if result.rowcount == 1:
                    return job_id, file_id

    def _process(self, job_id: UUID, file_id: UUID, now: datetime) -> WorkerResult:
        with self.factory() as session:
            record = session.get(FileRecord, file_id)
            if record is None:
                raise RuntimeError("FileRecordMissing")
            try:
                detected_media_type = self.validator(
                    self.storage.quarantine_path(record.storage_key),
                    record.declared_media_type,
                )
            except ContentRejectedError:
                return self._reject(session, job_id, record, now)

            self.storage.promote(record.storage_key)
            try:
                job = self._processing_job(session, job_id)
                record.detected_media_type = detected_media_type
                record.state = "READY"
                job.state = "COMPLETED"
                job.claimed_at = None
                job.last_error = None
                session.add(
                    AuditRecord(
                        file_id=file_id,
                        actor_id=SYSTEM_ACTOR_ID,
                        action="FILE_READY",
                        occurred_at=now,
                    )
                )
                session.commit()
            except SQLAlchemyError:
                session.rollback()
                self.storage.restore_quarantine(record.storage_key)
                raise
            return WorkerResult(job_id, file_id, "COMPLETED")

    def _reject(
        self,
        session: Session,
        job_id: UUID,
        record: FileRecord,
        now: datetime,
    ) -> WorkerResult:
        job = self._processing_job(session, job_id)
        record.state = "REJECTED"
        job.state = "COMPLETED"
        job.claimed_at = None
        job.last_error = "ContentRejectedError"
        self.storage.stage_rejection(record.storage_key)
        session.add(
            AuditRecord(
                file_id=record.id,
                actor_id=SYSTEM_ACTOR_ID,
                action="FILE_REJECTED",
                occurred_at=now,
            )
        )
        try:
            session.commit()
        except SQLAlchemyError:
            session.rollback()
            self.storage.restore_rejection(record.storage_key)
            raise
        try:
            self.storage.delete_rejected(record.storage_key)
        except OSError:
            LOGGER.exception(
                "Rejected-object cleanup failed",
                extra={"file_id": str(record.id), "job_id": str(job_id)},
            )
        return WorkerResult(job_id, record.id, "COMPLETED")

    def _record_failure(
        self,
        job_id: UUID,
        file_id: UUID,
        error: Exception,
        now: datetime,
    ) -> WorkerResult:
        with self.factory() as session:
            job = self._processing_job(session, job_id)
            terminal = job.attempt_count >= self.max_attempts
            job.state = "DEAD_LETTER" if terminal else "PENDING"
            job.claimed_at = None
            job.last_error = type(error).__name__[:120]
            if not terminal:
                delay = self.retry_base_seconds * (2 ** (job.attempt_count - 1))
                job.next_attempt_at = now + timedelta(seconds=delay)
            session.add(
                AuditRecord(
                    file_id=file_id,
                    actor_id=SYSTEM_ACTOR_ID,
                    action="JOB_DEAD_LETTER" if terminal else "JOB_RETRY_SCHEDULED",
                    occurred_at=now,
                )
            )
            session.commit()
            return WorkerResult(job_id, file_id, job.state)

    @staticmethod
    def _processing_job(session: Session, job_id: UUID) -> ProcessingJob:
        job = session.get(ProcessingJob, job_id)
        if job is None or job.state != "PROCESSING":
            raise RuntimeError("ProcessingJobMissingOrNotClaimed")
        return job
