# CloudFileFlow demo guide

This guide helps demonstrate CloudFileFlow as an independent portfolio project
for safe synthetic file ingestion and background processing. Use generated
sample files only. Do not upload candidate records, employer documents,
credentials, confidential files, or malware samples.

## What to prove in a short demo

- The API accepts an authenticated, bounded, allowlisted upload into quarantine.
- Idempotency prevents duplicate file/job records for the same safe key.
- A worker validates content, promotes valid objects, records audit events, and
  exposes owner-scoped status.
- Downloads are available only after a file reaches `READY`.
- The operator endpoint exposes sanitized job counts/dead letters without file
  bodies, filenames, owner identifiers, or raw exception messages.
- SQLite/filesystem adapters are explicitly local substitutes, not cloud
  execution evidence.

## Pre-demo verification

Run the local gate described in the README:

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

If Docker is not available, say clearly that image build, Compose health,
LocalStack/cloud-emulator behavior, remote CI, and deployment remain pending.

## Local API flow

1. Create an ignored `.env` from `.env.example`, replacing the signing secret
   and operator owner ID with local-only values.
2. Apply migrations:

   ```powershell
   .\.venv\Scripts\alembic.exe upgrade head
   ```

3. Start the API:

   ```powershell
   .\.venv\Scripts\uvicorn.exe cloudfileflow.app:create_app --factory
   ```

4. In a second terminal, create a synthetic sample:

   ```powershell
   Set-Content -LiteralPath .\tmp-demo-upload.txt -Value "Synthetic demo file"
   ```

5. Generate a short-lived local bearer token with PyJWT using the same local
   signing secret and issuer configured in `.env`.
6. Upload the synthetic file with a unique idempotency key:

   ```powershell
   curl.exe -X POST http://127.0.0.1:8000/api/v1/files `
     -H "Authorization: Bearer <local-demo-token>" `
     -H "Idempotency-Key: demo-upload-001" `
     -F "file=@tmp-demo-upload.txt;type=text/plain"
   ```

7. Capture the returned file ID.
8. Run the one-shot worker:

   ```powershell
   .\.venv\Scripts\cloudfileflow-worker.exe
   ```

9. Retrieve metadata, job state, audit history, and content for that file ID.
10. Re-run the same upload with the same idempotency key and explain why it
    returns the original resource instead of creating a duplicate.
11. Upload a deliberately invalid synthetic file, run the worker, and show the
    rejected/dead-letter path if you want to discuss failure handling.
12. Open `/docs` to show the OpenAPI surface.

## Suggested two-minute narration

“CloudFileFlow is a local-first file ingestion system that treats uploads as
untrusted. The API streams a bounded synthetic file into quarantine, stores
metadata and a processing job transactionally, and a worker validates content
before promotion. The interesting engineering pieces are idempotency, retry and
dead-letter state, owner-scoped reads, audit history, and sanitized operator
visibility. The current implementation uses SQLite and the filesystem as
honest local adapters; Docker, LocalStack, cloud services, remote CI, and
deployment are not claimed until those checks run.”

## Evidence to show during the demo

- `README.md` status, setup, and limits.
- `docs/ARCHITECTURE.md` for the API/worker/storage boundaries.
- `docs/THREAT_MODEL.md` for file-safety assumptions.
- `docs/OPERATIONS.md` for logs, rollback, and runtime limits.
- `docs/INTERVIEW_GUIDE.md` for deeper explanation.

## Do not claim

- Real malware scanning.
- S3, SQS, Lambda, LocalStack, container, remote CI, or deployment execution
  before those paths are verified and recorded.
- That local content checks prove arbitrary files are safe.
- Security completeness or production traffic.
