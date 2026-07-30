from pathlib import Path
from uuid import UUID

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CLOUDFILEFLOW_",
        env_file=".env",
        extra="ignore",
    )

    database_url: str = "sqlite:///./data/cloudfileflow.sqlite3"
    storage_root: Path = Path("./data/storage")
    auto_migrate: bool = False
    jwt_secret: SecretStr
    jwt_issuer: str = "cloudfileflow-local"
    operator_owner_id: UUID | None = None
    max_file_bytes: int = 5 * 1024 * 1024
    worker_max_attempts: int = Field(default=3, ge=1, le=10)
    worker_retry_base_seconds: int = Field(default=5, ge=1, le=3600)
    worker_claim_timeout_seconds: int = Field(default=300, ge=30, le=86_400)
    worker_poll_seconds: float = Field(default=1.0, ge=0.1, le=60)

    @field_validator("jwt_secret")
    @classmethod
    def validate_signing_secret(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError("JWT secret must contain at least 32 characters")
        return value

    @field_validator("max_file_bytes")
    @classmethod
    def validate_file_limit(cls, value: int) -> int:
        if value < 1 or value > 25 * 1024 * 1024:
            raise ValueError("file limit must be between 1 byte and 25 MiB")
        return value
