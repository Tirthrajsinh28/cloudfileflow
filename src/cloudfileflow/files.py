import re
from datetime import datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    Header,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse as DownloadResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from cloudfileflow.config import Settings
from cloudfileflow.database import AuditRecord, FileRecord, ProcessingJob, get_session, utc_now
from cloudfileflow.identity import Principal, current_principal, get_settings
from cloudfileflow.storage import EmptyUploadError, FileTooLargeError, LocalStorage

ALLOWED_MEDIA_TYPES = frozenset({"application/pdf", "application/json", "text/plain"})
IDEMPOTENCY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")

router = APIRouter(prefix="/api/v1/files", tags=["files"])


class FileResponse(BaseModel):
    id: UUID
    display_name: str
    declared_media_type: str
    byte_size: int
    sha256: str
    state: str
    created_at: datetime

    @classmethod
    def from_record(cls, record: FileRecord) -> "FileResponse":
        return cls(
            id=record.id,
            display_name=record.display_name,
            declared_media_type=record.declared_media_type,
            byte_size=record.byte_size,
            sha256=record.sha256,
            state=record.state,
            created_at=record.created_at,
        )


class JobResponse(BaseModel):
    id: UUID
    state: str
    attempt_count: int
    next_attempt_at: datetime
    last_error: str | None


class AuditResponse(BaseModel):
    action: str
    occurred_at: datetime


def get_storage(request: Request) -> LocalStorage:
    return request.app.state.storage  # type: ignore[no-any-return]


def display_name(filename: str | None) -> str:
    if not filename:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A filename is required.")
    candidate = filename.replace("\\", "/").split("/")[-1].strip()
    if not candidate or len(candidate) > 255 or any(ord(char) < 32 for char in candidate):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The filename is invalid.")
    return candidate


def idempotency_key(value: str) -> str:
    if not IDEMPOTENCY_PATTERN.fullmatch(value):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Idempotency-Key must contain 8-128 safe characters.",
        )
    return value


@router.post("", response_model=FileResponse, status_code=status.HTTP_201_CREATED)
async def upload_file(
    response: Response,
    principal: Annotated[Principal, Depends(current_principal)],
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[Session, Depends(get_session)],
    storage: Annotated[LocalStorage, Depends(get_storage)],
    upload: Annotated[UploadFile, File()],
    raw_idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> FileResponse:
    key = idempotency_key(raw_idempotency_key)
    existing = session.scalar(
        select(FileRecord).where(
            FileRecord.owner_id == principal.owner_id,
            FileRecord.idempotency_key == key,
        )
    )
    if existing is not None:
        await upload.close()
        response.status_code = status.HTTP_200_OK
        return FileResponse.from_record(existing)
    if upload.content_type not in ALLOWED_MEDIA_TYPES:
        await upload.close()
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Media type is not allowed.")

    name = display_name(upload.filename)
    file_id = uuid4()
    try:
        stored = await storage.put_quarantine(file_id, upload, settings.max_file_bytes)
    except FileTooLargeError:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            "File exceeds the size limit.",
        ) from None
    except EmptyUploadError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "File must not be empty.") from None

    now = utc_now()
    record = FileRecord(
        id=file_id,
        owner_id=principal.owner_id,
        idempotency_key=key,
        display_name=name,
        storage_key=stored.storage_key,
        declared_media_type=upload.content_type,
        byte_size=stored.byte_size,
        sha256=stored.digest,
        state="QUARANTINED",
        created_at=now,
    )
    try:
        session.add(record)
        session.flush()
        session.add_all(
            [
                ProcessingJob(
                    file_id=file_id,
                    state="PENDING",
                    next_attempt_at=now,
                    created_at=now,
                ),
                AuditRecord(
                    file_id=file_id,
                    actor_id=principal.owner_id,
                    action="FILE_QUARANTINED",
                    occurred_at=now,
                ),
            ]
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        storage.delete_quarantine(stored.storage_key)
        concurrent = session.scalar(
            select(FileRecord).where(
                FileRecord.owner_id == principal.owner_id,
                FileRecord.idempotency_key == key,
            )
        )
        if concurrent is None:
            raise
        response.status_code = status.HTTP_200_OK
        return FileResponse.from_record(concurrent)
    except SQLAlchemyError:
        session.rollback()
        storage.delete_quarantine(stored.storage_key)
        raise
    response.headers["Location"] = f"/api/v1/files/{file_id}"
    return FileResponse.from_record(record)


@router.get("/{file_id}", response_model=FileResponse)
def get_file(
    file_id: UUID,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> FileResponse:
    record = session.scalar(
        select(FileRecord).where(
            FileRecord.id == file_id,
            FileRecord.owner_id == principal.owner_id,
        )
    )
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File was not found.")
    return FileResponse.from_record(record)


@router.get("/{file_id}/job", response_model=JobResponse)
def get_file_job(
    file_id: UUID,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> JobResponse:
    record = _owner_file(session, file_id, principal.owner_id)
    job = session.scalar(select(ProcessingJob).where(ProcessingJob.file_id == record.id))
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Processing job was not found.")
    return JobResponse.model_validate(job, from_attributes=True)


@router.get("/{file_id}/audit", response_model=list[AuditResponse])
def get_file_audit(
    file_id: UUID,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> list[AuditResponse]:
    record = _owner_file(session, file_id, principal.owner_id)
    events = session.scalars(
        select(AuditRecord)
        .where(AuditRecord.file_id == record.id)
        .order_by(AuditRecord.occurred_at, AuditRecord.id)
    )
    return [AuditResponse.model_validate(event, from_attributes=True) for event in events]


@router.get("/{file_id}/content", response_class=DownloadResponse)
def download_file(
    file_id: UUID,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[Session, Depends(get_session)],
    storage: Annotated[LocalStorage, Depends(get_storage)],
) -> DownloadResponse:
    record = _owner_file(session, file_id, principal.owner_id)
    if record.state != "READY" or record.detected_media_type is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "File is not ready for download.")
    path = storage.ready_path(record.storage_key)
    if not path.is_file():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "File content is unavailable.")
    return DownloadResponse(
        path,
        media_type=record.detected_media_type,
        filename=record.display_name,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


def _owner_file(session: Session, file_id: UUID, owner_id: UUID) -> FileRecord:
    record = session.scalar(
        select(FileRecord).where(
            FileRecord.id == file_id,
            FileRecord.owner_id == owner_id,
        )
    )
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File was not found.")
    return record
