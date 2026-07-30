# CloudFileFlow Operations

Status: Local runbook. Container commands are configured but unexecuted in the
current Docker-less environment.

## Required configuration

| Variable | Required | Purpose |
| --- | --- | --- |
| `CLOUDFILEFLOW_DATABASE_URL` | No | SQLAlchemy URL; local default is SQLite under `./data`. |
| `CLOUDFILEFLOW_STORAGE_ROOT` | No | Private quarantine, clean, and rejected-object root. |
| `CLOUDFILEFLOW_JWT_SECRET` | Yes | Development HS256 key, at least 32 characters. |
| `CLOUDFILEFLOW_JWT_ISSUER` | No | Required token issuer. |
| `CLOUDFILEFLOW_OPERATOR_OWNER_ID` | For operator API | UUID allowed to read global job operations. |
| `CLOUDFILEFLOW_MAX_FILE_BYTES` | No | Streaming byte limit, 1 byte through 25 MiB. |
| `CLOUDFILEFLOW_WORKER_MAX_ATTEMPTS` | No | Retry ceiling, 1 through 10. |
| `CLOUDFILEFLOW_WORKER_RETRY_BASE_SECONDS` | No | Exponential-delay base. |
| `CLOUDFILEFLOW_WORKER_CLAIM_TIMEOUT_SECONDS` | No | Stale-claim threshold. |
| `CLOUDFILEFLOW_WORKER_POLL_SECONDS` | No | Daemon idle interval, 0.1 through 60 seconds. |
| `CLOUDFILEFLOW_AUTO_MIGRATE` | No | Explicit local/test convenience; defaults off. |

Never commit `.env`. Rotate a disclosed JWT key and consider every token signed
by it compromised.

## Process order

1. Run `alembic upgrade head`.
2. Start the API with Uvicorn.
3. Start `cloudfileflow-worker-daemon`.
4. Verify `/health`.
5. Inspect JSON logs for `request_completed`, `worker_started`, and
   `job_finished`.

The API and worker refuse a database that is not at the current migration head.

## Compose

Compose runs a one-shot migration service before the API and worker. The API is
bound only to `127.0.0.1:8085`. The database and object namespaces share the
`cloudfileflow-data` volume.

```powershell
docker compose up --build --wait
curl.exe --fail http://127.0.0.1:8085/health
docker compose ps
docker compose logs --no-color
```

Docker execution remains unverified locally.

## Stop, rollback, and reset

Normal stop retains synthetic data:

```powershell
docker compose down
```

To roll back application code, stop the topology, check out the prior reviewed
release, rebuild, and run its documented migration compatibility check before
startup. The initial migration has a downgrade for local development, but a
database downgrade is not an automatic production rollback strategy.

Intentional destructive reset:

```powershell
docker compose down --volumes --remove-orphans
```

This deletes every synthetic database row and stored object in the named
volume.

## Backup and recovery

For the local adapter, stop API and worker writes before copying the SQLite
database plus the entire storage root together. Copying only one side can
produce missing or orphaned objects. No automated backup, point-in-time
recovery, or reconciliation command exists.

## Operational limits

- SQLite/filesystem are local adapters, not multi-node or cloud durability.
- One polling worker is the reviewed topology.
- Failed jobs are inspectable but cannot be replayed.
- Reconciliation, rate limiting, metrics export, alerting, S3/SQS/LocalStack,
  real malware scanning, and external deployment are pending.
- JSON logs intentionally exclude tokens, query strings, filenames, bodies,
  owner IDs, and exception messages.
