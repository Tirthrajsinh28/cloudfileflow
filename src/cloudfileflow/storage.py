from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from uuid import UUID

from fastapi import UploadFile


class EmptyUploadError(ValueError):
    pass


class FileTooLargeError(ValueError):
    pass


@dataclass(frozen=True)
class StoredObject:
    storage_key: str
    byte_size: int
    digest: str


class LocalStorage:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.quarantine = self.root / "quarantine"
        self.clean = self.root / "clean"
        self.rejected = self.root / "rejected"
        self.temporary = self.quarantine / ".tmp"
        self.quarantine.mkdir(parents=True, exist_ok=True)
        self.clean.mkdir(parents=True, exist_ok=True)
        self.rejected.mkdir(parents=True, exist_ok=True)
        self.temporary.mkdir(parents=True, exist_ok=True)

    async def put_quarantine(
        self,
        file_id: UUID,
        upload: UploadFile,
        max_bytes: int,
    ) -> StoredObject:
        storage_key = file_id.hex
        temporary_path = self.temporary / f"{storage_key}.part"
        final_path = self.quarantine / storage_key
        digest = sha256()
        byte_size = 0
        try:
            with temporary_path.open("xb") as destination:
                while chunk := await upload.read(64 * 1024):
                    byte_size += len(chunk)
                    if byte_size > max_bytes:
                        raise FileTooLargeError
                    digest.update(chunk)
                    destination.write(chunk)
            if byte_size == 0:
                raise EmptyUploadError
            temporary_path.replace(final_path)
        except BaseException:
            temporary_path.unlink(missing_ok=True)
            final_path.unlink(missing_ok=True)
            raise
        finally:
            await upload.close()
        return StoredObject(storage_key, byte_size, digest.hexdigest())

    def delete_quarantine(self, storage_key: str) -> None:
        (self.quarantine / storage_key).unlink(missing_ok=True)

    def quarantine_path(self, storage_key: str) -> Path:
        return self.quarantine / storage_key

    def promote(self, storage_key: str) -> Path:
        destination = self.clean / storage_key
        self.quarantine_path(storage_key).replace(destination)
        return destination

    def restore_quarantine(self, storage_key: str) -> None:
        ready_path = self.ready_path(storage_key)
        if ready_path.exists():
            ready_path.replace(self.quarantine_path(storage_key))

    def ready_path(self, storage_key: str) -> Path:
        return self.clean / storage_key

    def stage_rejection(self, storage_key: str) -> None:
        self.quarantine_path(storage_key).replace(self.rejected / storage_key)

    def restore_rejection(self, storage_key: str) -> None:
        rejected_path = self.rejected / storage_key
        if rejected_path.exists():
            rejected_path.replace(self.quarantine_path(storage_key))

    def delete_rejected(self, storage_key: str) -> None:
        (self.rejected / storage_key).unlink(missing_ok=True)
