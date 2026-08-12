from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from cloudfileflow.config import Settings
from cloudfileflow.database import AuditRecord, ProcessingJob, get_session, utc_now
from cloudfileflow.identity import Principal, current_principal, get_settings

router = APIRouter(prefix="/api/v1/operations", tags=["operations"])


class JobCounts(BaseModel):
    pending: int
    processing: int
    completed: int
    dead_letter: int


class DeadLetterJob(BaseModel):
    id: UUID
    file_id: UUID
    attempt_count: int
    last_error: str | None
    created_at: datetime


class JobOperationsResponse(BaseModel):
    counts: JobCounts
    dead_letter_jobs: list[DeadLetterJob]


class ReplayJobResponse(BaseModel):
    id: UUID
    file_id: UUID
    state: str
    attempt_count: int


def require_operator(principal: Principal, settings: Settings) -> None:
    if settings.operator_owner_id is None or principal.owner_id != settings.operator_owner_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Operator access is required.")


@router.get("/jobs", response_model=JobOperationsResponse)
def job_operations(
    principal: Annotated[Principal, Depends(current_principal)],
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[Session, Depends(get_session)],
) -> JobOperationsResponse:
    require_operator(principal, settings)

    rows = session.execute(
        select(ProcessingJob.state, func.count())
        .group_by(ProcessingJob.state)
        .order_by(ProcessingJob.state)
    )
    counts = {state: count for state, count in rows}
    failures = session.scalars(
        select(ProcessingJob)
        .where(ProcessingJob.state == "DEAD_LETTER")
        .order_by(ProcessingJob.created_at.desc(), ProcessingJob.id)
        .limit(50)
    )
    return JobOperationsResponse(
        counts=JobCounts(
            pending=counts.get("PENDING", 0),
            processing=counts.get("PROCESSING", 0),
            completed=counts.get("COMPLETED", 0),
            dead_letter=counts.get("DEAD_LETTER", 0),
        ),
        dead_letter_jobs=[
            DeadLetterJob.model_validate(job, from_attributes=True) for job in failures
        ],
    )


@router.post("/jobs/{job_id}/replay", response_model=ReplayJobResponse)
def replay_dead_letter_job(
    job_id: UUID,
    principal: Annotated[Principal, Depends(current_principal)],
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[Session, Depends(get_session)],
) -> ReplayJobResponse:
    require_operator(principal, settings)
    job = session.get(ProcessingJob, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Processing job was not found.")
    if job.state != "DEAD_LETTER":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only dead-letter jobs can be replayed.")

    now = utc_now()
    result = session.execute(
        update(ProcessingJob)
        .where(ProcessingJob.id == job_id, ProcessingJob.state == "DEAD_LETTER")
        .values(
            state="PENDING",
            attempt_count=0,
            next_attempt_at=now,
            claimed_at=None,
            last_error=None,
        )
    )
    if not isinstance(result, CursorResult) or result.rowcount != 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only dead-letter jobs can be replayed.")

    session.add(
        AuditRecord(
            file_id=job.file_id,
            actor_id=principal.owner_id,
            action="JOB_REPLAYED",
            occurred_at=now,
        )
    )
    session.commit()
    session.refresh(job)
    return ReplayJobResponse.model_validate(job, from_attributes=True)
