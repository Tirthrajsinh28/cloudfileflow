# CloudFileFlow

CloudFileFlow is an independent portfolio project for secure, traceable file
ingestion and background processing using synthetic documents.

## Status

The complete local vertical slice is implemented and locally verified. It
streams bounded allowlisted uploads into quarantine, atomically creates
metadata/job/audit records, validates content in a one-shot worker, promotes
valid objects, rejects malformed content, retries transient failures with
exponential delay, recovers stale claims, and moves exhausted jobs to a
dead-letter state. Owners can inspect status/audit history and download only
`READY` content; a separately configured operator can inspect bounded job
counts, sanitized dead-letter records, and replay dead-letter jobs through an
audited state-guarded endpoint.

Alembic manages the SQLite schema, HTTP errors use problem details, and
request/job events are JSON-structured with bounded correlation IDs. No cloud
emulator, container, CI execution, or external deployment is claimed yet.

The local vertical slice uses:

- Python 3.13 and FastAPI.
- SQLAlchemy with SQLite as an explicit local persistence/queue substitute.
- A local quarantine/clean-storage adapter.
- JWT bearer validation for synthetic development principals.
- Size, media-type, filename, and content checks before a file becomes
  downloadable.
- Idempotent upload requests, durable job state, audit records, retries, and a
  dead-letter state with operator-only replay.

SQLite and the local filesystem are development adapters, not evidence of AWS
S3, SQS, Lambda, or malware-scanner execution.

See `docs/PRODUCT_SPEC.md`, `docs/THREAT_MODEL.md`,
`docs/ARCHITECTURE.md`, `docs/DEMO_GUIDE.md`, `CHANGELOG.md`, and
`SECURITY.md` for the design, limits, current local release-note draft,
demonstration flow, and security reporting policy.

## API surface

| Route | Purpose |
| --- | --- |
| `GET /health` | Public liveness response. |
| `GET /api/v1/me` | Validated synthetic principal. |
| `POST /api/v1/files` | Authenticated multipart quarantine upload. |
| `GET /api/v1/files/{id}` | Owner-scoped metadata. |
| `GET /api/v1/files/{id}/job` | Owner-scoped processing state. |
| `GET /api/v1/files/{id}/audit` | Owner-scoped chronological audit events. |
| `GET /api/v1/files/{id}/content` | Attachment download for `READY` content only. |
| `GET /api/v1/operations/jobs` | Configured-operator counts and bounded dead letters. |
| `POST /api/v1/operations/jobs/{id}/replay` | Configured-operator replay for `DEAD_LETTER` jobs only. |

OpenAPI is available at `/docs` and `/openapi.json`.

## Local setup and verification

The hash lock is generated for Python 3.13 on Windows. Install locked
dependencies, then the local package without dependency resolution:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install pip==26.1.2
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements-build.lock
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements-dev.lock
.\.venv\Scripts\python.exe -m pip install --no-build-isolation --no-deps -e .
```

Copy `.env.example` to an ignored `.env`, replace the JWT secret and operator
UUID, then migrate and start the API:

```powershell
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\uvicorn.exe cloudfileflow.app:create_app --factory
```

Process one due job:

```powershell
.\.venv\Scripts\cloudfileflow-worker.exe
```

Run the continuously polling worker used by the container topology:

```powershell
.\.venv\Scripts\cloudfileflow-worker-daemon.exe
```

Application and worker startup fail when the database is not at the current
Alembic revision. `CLOUDFILEFLOW_AUTO_MIGRATE=true` exists only as an explicit
test/local convenience; it defaults to `false`.

`requirements.lock` is the hash-locked runtime dependency set used by the
image. `requirements-build.lock` closes the PEP 517 build-tool boundary, and
`requirements-dev.lock` adds the exact lint, type, test, build, lock, and audit
tools used by contributors and CI.

Run the current gate:

```powershell
.\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\mypy.exe
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\alembic.exe check
.\.venv\Scripts\alembic.exe current
.\.venv\Scripts\coverage.exe run -m pytest
.\.venv\Scripts\coverage.exe report --fail-under=80
.\.venv\Scripts\pip-audit.exe --skip-editable
```

The latest local gate has 36 passing tests and 90% reported coverage. That
evidence covers the local adapters and current API/worker paths only. It
does not prove PostgreSQL, S3, SQS, LocalStack, container, CI, or deployment
behavior.

## Container and CI state

The image uses a digest-pinned Python 3.13.14 slim base, installs the runtime
hash lock, runs as UID/GID 10001, and includes an HTTP health check. Compose
defines an ordered migration job, API, and polling worker on one private named
volume. Runtime services use a read-only root filesystem, no added Linux
capabilities, and `no-new-privileges`.

Create an ignored `.env` with a random JWT secret and operator UUID, then:

```powershell
docker compose up --build --wait
docker compose logs --follow
docker compose down
```

`docker compose down --volumes` permanently removes the local synthetic
database and objects; use it only for an intentional reset. Docker is
unavailable in the current verification environment, so image build, Compose
health, and teardown are configured and structurally checked but not claimed
as executed locally. GitHub Actions defines the complete Python gate plus a
container smoke job, but no remote run exists yet.

See `docs/OPERATIONS.md` for environment, logs, rollback, backup, and limits.

## Cost and data policy

The current cost ceiling is CAD 0. Use only generated fixtures and synthetic
documents. Never upload candidate records, employer material, credentials, or
confidential files.

LocalStack is intentionally not included as a decorative service: there is no
S3/SQS adapter yet, and Docker is unavailable. The local filesystem/SQLite
contracts remain the honest executable substitute until an emulator-backed
adapter and its tests can be run.

## License

MIT
