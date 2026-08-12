from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import jwt
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from cloudfileflow.app import create_app
from cloudfileflow.config import Settings

SECRET = "synthetic-test-signing-secret-32-characters"
ISSUER = "cloudfileflow-test"
OWNER_ID = UUID("d1111111-1111-1111-1111-111111111111")


def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'cloudfileflow.sqlite3'}",
        storage_root=tmp_path / "storage",
        auto_migrate=True,
        jwt_secret=SecretStr(SECRET),
        jwt_issuer=ISSUER,
        max_file_bytes=1024,
    )


def token(
    *,
    secret: str = SECRET,
    issuer: str = ISSUER,
    subject: str = str(OWNER_ID),
    expires_delta: timedelta = timedelta(minutes=5),
) -> str:
    return jwt.encode(
        {
            "sub": subject,
            "iss": issuer,
            "exp": datetime.now(UTC) + expires_delta,
        },
        secret,
        algorithm="HS256",
    )


def test_health_is_public_and_descriptive(tmp_path: Path) -> None:
    with TestClient(create_app(settings(tmp_path))) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "UP", "service": "cloudfileflow"}


def test_valid_bearer_token_returns_owner(tmp_path: Path) -> None:
    with TestClient(create_app(settings(tmp_path))) as client:
        response = client.get(
            "/api/v1/me",
            headers={"Authorization": f"Bearer {token()}"},
        )

    assert response.status_code == 200
    assert response.json() == {"ownerId": str(OWNER_ID)}


def test_missing_invalid_and_expired_tokens_share_generic_failure(tmp_path: Path) -> None:
    with TestClient(create_app(settings(tmp_path))) as client:
        responses = [
            client.get("/api/v1/me"),
            client.get(
                "/api/v1/me",
                headers={
                    "Authorization": ("Bearer " + token(secret="wrong-secret-value-for-test-only"))
                },
            ),
            client.get(
                "/api/v1/me",
                headers={"Authorization": f"Bearer {token(expires_delta=timedelta(seconds=-1))}"},
            ),
            client.get(
                "/api/v1/me",
                headers={"Authorization": f"Bearer {token(subject='not-a-uuid')}"},
            ),
        ]

    for response in responses:
        assert response.status_code == 401
        assert response.json() == {
            "type": "about:blank",
            "title": "Unauthorized",
            "status": 401,
            "detail": "Authentication failed.",
            "instance": "/api/v1/me",
        }
        assert response.headers["content-type"] == "application/problem+json"
        assert response.headers["www-authenticate"] == "Bearer"


def test_settings_reject_weak_secret_and_unbounded_file_limit(tmp_path: Path) -> None:
    for overrides in (
        {"jwt_secret": SecretStr("too-short")},
        {
            "jwt_secret": SecretStr(SECRET),
            "max_file_bytes": 25 * 1024 * 1024 + 1,
        },
    ):
        try:
            Settings(
                storage_root=tmp_path,
                **overrides,
            )
        except ValidationError:
            continue
        raise AssertionError("unsafe settings were accepted")


def test_openapi_matches_routes_and_bearer_boundary(tmp_path: Path) -> None:
    with TestClient(create_app(settings(tmp_path))) as client:
        document = client.get("/openapi.json").json()

    assert document["info"]["title"] == "CloudFileFlow API"
    assert document["info"]["version"] == "0.1.0"
    assert set(document["paths"]) == {
        "/health",
        "/api/v1/me",
        "/api/v1/files",
        "/api/v1/files/{file_id}",
        "/api/v1/files/{file_id}/job",
        "/api/v1/files/{file_id}/audit",
        "/api/v1/files/{file_id}/content",
        "/api/v1/operations/jobs",
        "/api/v1/operations/jobs/{job_id}/replay",
    }
    scheme = document["components"]["securitySchemes"]["HTTPBearer"]
    assert scheme == {"type": "http", "scheme": "bearer"}
    assert "security" not in document["paths"]["/health"]["get"]
    assert document["paths"]["/api/v1/files"]["post"]["security"] == [{"HTTPBearer": []}]
    assert document["paths"]["/api/v1/operations/jobs"]["get"]["security"] == [{"HTTPBearer": []}]
    assert document["paths"]["/api/v1/operations/jobs/{job_id}/replay"]["post"]["security"] == [
        {"HTTPBearer": []}
    ]


def test_validation_and_missing_routes_use_problem_details(tmp_path: Path) -> None:
    with TestClient(create_app(settings(tmp_path))) as client:
        invalid = client.get(
            "/api/v1/files/not-a-uuid",
            headers={"Authorization": f"Bearer {token()}"},
        )
        missing = client.get("/route-that-does-not-exist")

    assert invalid.status_code == 422
    assert invalid.json()["detail"] == "Request validation failed."
    assert invalid.json()["instance"] == "/api/v1/files/not-a-uuid"
    assert invalid.json()["errors"][0]["location"] == "path.file_id"
    assert "input" not in invalid.text
    assert missing.status_code == 404
    assert missing.json() == {
        "type": "about:blank",
        "title": "Not Found",
        "status": 404,
        "detail": "Not Found",
        "instance": "/route-that-does-not-exist",
    }
