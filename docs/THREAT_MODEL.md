# CloudFileFlow Threat Model

Status: Initial design review. This is not a security guarantee.

## Assets and trust boundaries

- Uploaded bytes are untrusted.
- Bearer tokens and signing keys are secrets.
- File ownership, job state, audit history, and storage keys are integrity
  assets.
- The HTTP boundary, quarantine storage, metadata database, worker, clean
  storage, and download response are separate trust zones.

## Threats and planned controls

| Threat | Initial control |
| --- | --- |
| Oversize upload / memory exhaustion | Stream fixed-size chunks; stop above configured byte limit; never read the whole upload into memory. |
| Path traversal / hostile filename | Store under generated UUID keys; retain only a bounded display name; never join storage paths from user input. |
| Content-type spoofing | Allowlist declared media type and validate PDF signature, UTF-8 text, or JSON syntax in the worker. |
| Active/malicious content | Quarantine by default; never execute, render, or deserialize uploaded objects; document that signature checks are not malware scanning. |
| Cross-owner access / IDOR | Derive owner from validated JWT `sub`; scope metadata and downloads by owner at query time. |
| Replay / duplicate events | Require bounded idempotency key; unique owner/key constraint; stable job ID. |
| Retry storm | Bounded attempts, exponential delay, batch limits, terminal dead-letter state. |
| Partial database/storage failure | Temporary file plus atomic rename; compensate storage on transaction failure; reconciliation remains future work. |
| Secret leakage | Environment-only secret, redacted errors, no token/file-body logging, `.env` ignored. |
| Zip/archive bomb | Archives are outside the first allowlist. |
| Public object exposure | No static storage mount or user-derived object URL; API-authorized streaming only. |
| Race during download | Download only `READY`; use immutable content key and digest. |

## Explicit non-controls

- File signatures do not prove a file is malware-free.
- The local JWT key is not a production identity provider.
- SQLite locking is not proof of distributed queue correctness.
- The local filesystem is not S3 durability or authorization evidence.

## Review triggers

Revisit this model before adding archives, images, office documents, cloud
presigned URLs, external callbacks, operator replay, or a public deployment.
