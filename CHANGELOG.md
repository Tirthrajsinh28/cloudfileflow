# Changelog

## [Unreleased]

- Build the CloudFileFlow local file-ingestion slice with bounded uploads,
  quarantine storage, metadata persistence, job state, audit records,
  owner-scoped reads/downloads, and operator job summaries.
- Add content validation for safe synthetic PDF, JSON, and text examples,
  idempotent upload replay, retry behavior, stale-claim recovery, and
  dead-letter handling.
- Add Alembic-managed schema lifecycle, problem-detail responses, structured
  request/job logs, hash-locked runtime/dev dependencies, and local worker plus
  daemon entry points.
- Add Docker/Compose/CI configuration, Dependabot, pull-request template, and
  issue template with no-secret and synthetic-file guidance.
- Add local verification evidence for Ruff, strict mypy, pytest/coverage,
  Alembic, runtime smoke checks, build locks, and dependency audit.

Cloud emulator adapters, Docker/LocalStack execution, remote GitHub Actions,
deployment, screenshots, and release tag remain pending.
