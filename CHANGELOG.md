# Changelog

## [0.1.0] - 2026-07-30

- Build the CloudFileFlow local file-ingestion slice with bounded uploads,
  quarantine storage, metadata persistence, job state, audit records,
  owner-scoped reads/downloads, and operator job summaries.
- Add content validation for safe synthetic PDF, JSON, and text examples,
  idempotent upload replay, retry behavior, stale-claim recovery, and
  dead-letter handling.
- Add operator-only dead-letter replay with state guards, attempt reset,
  preserved job IDs, and `JOB_REPLAYED` audit records.
- Add Alembic-managed schema lifecycle, problem-detail responses, structured
  request/job logs, hash-locked runtime/dev dependencies, and local worker plus
  daemon entry points.
- Add Docker/Compose/CI configuration, Dependabot, pull-request template, and
  issue template with no-secret and synthetic-file guidance.
- Add local verification evidence for Ruff, strict mypy, pytest/coverage,
  Alembic, runtime smoke checks, build locks, and dependency audit.
- Add public GitHub Actions verification for the local SQLite/filesystem
  adapter stack, including verify and container/Compose jobs.

Cloud emulator adapters, LocalStack/S3/SQS/PostgreSQL execution, external
deployment, and screenshots/demo media remain pending.
