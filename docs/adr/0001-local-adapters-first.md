# ADR 0001: Local adapters before cloud emulation

Status: Accepted for the first slice.

## Decision

Implement storage and queue contracts with filesystem and SQLite adapters
before adding LocalStack S3/SQS.

## Why

Docker is unavailable, and the project must remain runnable at CAD 0. Local
adapters allow real streaming, authorization, idempotency, retry, and audit
behavior to be tested without pretending that AWS semantics were exercised.

## Consequences

- Faster deterministic tests and no cloud credentials.
- Adapter boundaries must avoid leaking filesystem/SQLite behavior.
- S3/SQS, visibility timeouts, IAM, encryption settings, and presigned URLs
  remain separate mandatory verification work.
