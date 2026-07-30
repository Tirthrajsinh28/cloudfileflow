# CloudFileFlow Interview Guide

Status: Local vertical slice implemented; answers must distinguish local
evidence from planned cloud/infrastructure work.

## Problem and users

Explain the need for quarantine, ownership, traceable jobs, bounded retries, and
authorized downloads for synthetic documents.

## Architecture

Describe the FastAPI boundary, local storage adapter, SQLAlchemy metadata/job
store, worker, clean namespace, and API download path. Main entities are file,
processing job, and audit record. The API and worker are separate processes
sharing explicit database and storage adapters.

## Database and main entities

Alembic creates three tables. `files` owns identity, ownership, display
metadata, generated storage key, digest, detected type, and state.
`processing_jobs` stores a stable job ID, claim/retry times, attempts, sanitized
error class, and state. `audit_records` append actor/action/time evidence for a
file. Foreign keys, state checks, nonempty bytes, and owner/idempotency
uniqueness are database constraints.

## Authentication and authorization

JWT validation pins HS256, issuer, expiry, and UUID subject. Every metadata,
job, audit, and download query includes that owner. The operator view is closed
unless the token subject matches an explicitly configured operator UUID. The
local signing key is development-only; there is no login or production identity
provider claim.

## API and error handling

Versioned routes use problem-detail errors, streaming limits, a required
idempotency header, generated IDs, and no storage-path disclosure. Valid
downloads are attachments with `private, no-store` and `nosniff` headers.

## Testing

Current unit/API/worker/migration tests cover anonymous and cross-owner denial,
oversize/type/filename/idempotency boundaries, content outcomes, retry delay,
dead letter, stale recovery, audit order, operator denial, downloads, OpenAPI,
problem responses, structured request IDs, migrations, and constraints. Cloud
adapter tests remain pending.

## CI/CD and deployment

GitHub Actions defines a clean hash install, format/lint/type/test/coverage,
Alembic drift, package build, audit, image build, and Compose health sequence.
The image is non-root and Compose orders migration before API/worker. Docker
and remote CI execution remain unverified. External deployment is not
implemented and the cost ceiling is CAD 0.

## Monitoring and security

JSON request/job events, correlation IDs, health, bounded error classes,
operator counts, and dead-letter inspection are implemented. There is no
metrics exporter, alerting system, or external log sink. Use the threat model;
never call signature validation malware scanning.

## Challenges and trade-offs

- Streaming limits versus framework convenience.
- Storage/database atomicity without a distributed transaction.
- Durable local queue semantics versus SQS visibility behavior.
- Direct downloads versus future presigned URLs.

## Known limitations and future improvements

Known limits include local symmetric JWTs, SQLite/filesystem adapters,
whole-object bounded validation in the worker, no reconciliation command, no
operator replay, and no rate limiting. Future work includes LocalStack,
PostgreSQL, a real scanning adapter, reconciliation, operator replay,
containers, CI, metrics, and deployment.

## Two-minute explanation

CloudFileFlow is an independent file-ingestion project designed around the rule
that uploads are untrusted. The local slice authenticates a synthetic owner,
streams a small allowlisted document into quarantine, commits metadata, a
durable job, and an audit record, then lets a bounded worker validate and
promote it for authorized download. It demonstrates idempotency, retries,
dead-letter handling, auditability, and IDOR protection. SQLite and the
filesystem are explicitly local adapters, not AWS evidence.

## Five-minute technical explanation

Cover trust boundaries, 64 KiB upload chunks, generated keys, the
storage/database compensation boundary, atomic state-guarded claims,
exponential retry, stale recovery, dead-letter state, audit events, ownership
queries, migration verification, structured logs, and the later S3/SQS adapter
contract.

## Demonstration script

1. Migrate an empty local database and start the API.
2. Upload the provided synthetic JSON with an idempotency key.
3. Repeat that key and show the same file ID with no duplicate job.
4. Run `cloudfileflow-worker` once.
5. Inspect `READY` metadata, completed job, and chronological audit.
6. Download as the owner and show cross-owner HTTP 404.
7. Use a test adapter failure to explain retry and dead-letter evidence.
8. End by stating that LocalStack, Docker, CI, and deployment remain pending.

## Likely questions and honest answer framework

- Why quarantine before download?
- Why are file signatures not malware scanning?
- How do you handle storage/database partial failure?
- How would SQS change claim semantics?
- How do you prevent IDOR?
- What remains unverified?

Answer framework: state what exists, cite the exact local verification, explain
the design trade-off, name what the evidence does not prove, and identify the
next defensible cloud step.
