# Contributing to CloudFileFlow

CloudFileFlow is an independent portfolio project for safe synthetic file
ingestion and background processing. Contributions should preserve its
defensive file-handling model and keep cloud claims aligned with verified
evidence.

## Ground rules

- Use synthetic sample files only.
- Do not upload confidential documents, candidate records, malware samples,
  private employer files, credentials, or personal data.
- Do not commit `.env` files, local databases, quarantine/clean-storage data,
  logs containing secrets, virtual environments, caches, build artifacts, or
  generated archives.
- Keep the local storage/queue path clearly labeled as a local adapter until a
  cloud emulator or cloud provider path is executed and recorded.
- Do not claim Docker, LocalStack, remote CI, or deployment evidence until those
  checks have run and are recorded.

## Local verification

Run from `projects/cloudfileflow` in the locked environment described in the
README:

```powershell
python -m ruff check .
python -m ruff format --check .
python -m mypy src tests
python -m pytest --cov=src --cov-report=term-missing
python -m pip_audit -r requirements.lock
```

Record the exact commands and results in the program status report before
describing a change as locally verified.

## File-safety expectations

- Preserve content-type and size restrictions.
- Preserve idempotency behavior and quarantine cleanup on duplicate requests or
  failed persistence.
- Keep invalid content out of clean storage.
- Keep downloads owner-scoped and available only for files that reached the
  `READY` state.
- Treat current validation as development safety checks, not malware scanning.

## Operations expectations

- Keep migrations reproducible from an empty database.
- Keep worker retry, dead-letter, and audit behavior deterministic.
- Keep operator responses sanitized; do not expose file contents, filenames,
  owner identifiers, or raw exception messages.
- Update `SECURITY.md`, `README.md`, and architecture docs when operational
  boundaries change.

## Pull request notes

Include:

- API, worker, migration, or storage behavior changed.
- Commands run and results.
- Whether Docker, LocalStack, remote CI, or deployment checks were executed.
- Any remaining limitations.
