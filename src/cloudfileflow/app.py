from typing import Annotated

from fastapi import Depends, FastAPI

from cloudfileflow.config import Settings
from cloudfileflow.database import create_database
from cloudfileflow.errors import install_exception_handlers
from cloudfileflow.files import router as files_router
from cloudfileflow.identity import Principal, current_principal
from cloudfileflow.migrations import upgrade_database, verify_database_revision
from cloudfileflow.observability import RequestObservabilityMiddleware, configure_json_logging
from cloudfileflow.operations import router as operations_router
from cloudfileflow.storage import LocalStorage


def create_app(settings: Settings | None = None) -> FastAPI:
    application = FastAPI(
        title="CloudFileFlow API",
        version="0.1.0",
        description=(
            "Secure synthetic-document ingestion using explicit local adapters. "
            "No live cloud integration is claimed."
        ),
    )
    configure_json_logging()
    application.add_middleware(RequestObservabilityMiddleware)
    install_exception_handlers(application)
    active_settings = settings or Settings()  # type: ignore[call-arg]
    active_settings.storage_root.parent.mkdir(parents=True, exist_ok=True)
    if active_settings.auto_migrate:
        upgrade_database(active_settings.database_url)
    engine, session_factory = create_database(active_settings.database_url)
    verify_database_revision(engine, active_settings.database_url)
    application.state.settings = active_settings
    application.state.session_factory = session_factory
    application.state.storage = LocalStorage(active_settings.storage_root)
    application.include_router(files_router)
    application.include_router(operations_router)

    @application.get("/health", tags=["operations"])
    def health() -> dict[str, str]:
        return {"status": "UP", "service": "cloudfileflow"}

    @application.get("/api/v1/me", tags=["identity"])
    def me(
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> dict[str, str]:
        return {"ownerId": str(principal.owner_id)}

    return application
