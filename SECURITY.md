# Security Policy

CloudFileFlow is an independent portfolio project for safe synthetic file
ingestion and local background processing. It is not a malware scanner and does
not process confidential documents or candidate records.

## Supported scope

Security review currently applies to the local FastAPI application, SQLite and
filesystem adapters, JWT validation, upload constraints, worker behavior,
Docker/CI configuration, dependency locks, and documentation.

## Reporting

No public vulnerability-reporting email address is published yet because public
contact details still require candidate confirmation. Before public release,
enable GitHub private vulnerability reporting or repository security advisories.

Do not open public issues containing secrets, malware samples, confidential
documents, candidate records, access tokens, `.env` values, or private logs.

## Current controls

- JWT bearer tokens pin HS256 and validate issuer, expiry, and UUID subjects.
- Uploads are bounded by size, filename metadata limits, declared content type,
  and content checks before files become downloadable.
- Objects begin in quarantine and only owner-scoped `READY` content can be
  downloaded.
- Job retries, stale-claim recovery, and dead-letter states are bounded.
- Operator job views are explicitly configured and omit owner IDs, filenames,
  file content, and raw exception messages.
- Runtime and development dependencies are hash-locked for local verification.

## Current limitations

- Content checks are signature/syntax checks, not malware detection.
- Local SQLite/filesystem adapters are not AWS S3/SQS/Lambda evidence.
- Docker/LocalStack, remote GitHub Actions, cloud deployment, key rotation,
  rate limits, reconciliation, and replay controls remain future work.
