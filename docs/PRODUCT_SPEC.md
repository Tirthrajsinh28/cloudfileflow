# CloudFileFlow Product Specification

Status: Local vertical-slice acceptance criteria are implemented and locally
verified. Emulator, container, CI, and deployment criteria remain pending.

## Problem and users

Fictional application teams need to accept synthetic documents without making
uploaded bytes immediately trusted, losing job state, or retrying work
silently. Uploaders need ownership-scoped status and downloads. Operators need
bounded visibility into retries and dead-letter jobs.

## First vertical slice

- JWT-authenticated synthetic principals.
- Multipart upload with a required idempotency key.
- PDF, plain-text, and JSON allowlist.
- Five MiB default size limit enforced while streaming.
- Server-generated storage names and preserved display metadata.
- Quarantine storage; no direct public file path.
- Metadata, processing job, and audit row committed together.
- Worker validation, SHA-256 digest, retry, and dead-letter state.
- Owner-scoped metadata and authorized download after processing.
- Operator-only dead-letter inspection and audited replay.
- Structured logs and health endpoint.

## State model

File: `QUARANTINED -> READY | REJECTED`.

Job: `PENDING -> PROCESSING -> COMPLETED`, with failures returning to
`PENDING` until the configured maximum and then moving to `DEAD_LETTER`.

## Acceptance criteria

- `VERIFIED` No default signing secret.
- `VERIFIED` Anonymous and cross-owner access denied.
- `VERIFIED` Oversize, disallowed, malformed, and filename-traversal inputs rejected.
- `VERIFIED` Duplicate idempotency keys return the original resource without duplicate
  storage/jobs.
- `VERIFIED` State, job, and audit writes are transactional.
- `VERIFIED` Downloads never expose quarantine paths.
- `VERIFIED` Retries are bounded and observable.
- `VERIFIED` Dead-letter replay is operator-only, state-guarded, and audited.
- `VERIFIED` Tests use only generated synthetic fixtures.
- `VERIFIED` Local adapters are labeled; AWS behavior is not claimed.

## Deferred

S3/SQS/LocalStack adapters, multipart cloud upload, real malware scanning,
presigned URLs, reconciliation, web dashboard, containers, CI, and deployment.
