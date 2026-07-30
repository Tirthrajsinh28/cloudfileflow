from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cloudfileflow.config import Settings
from cloudfileflow.database import ProcessingJob, get_session
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


@router.get("/jobs", response_model=JobOperationsResponse)
def job_operations(
    principal: Annotated[Principal, Depends(current_principal)],
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[Session, Depends(get_session)],
) -> JobOperationsResponse:
    if settings.operator_owner_id is None or principal.owner_id != settings.operator_owner_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Operator access is required.")

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
