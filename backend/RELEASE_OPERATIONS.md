# BulletFeed MVP release operations

The release stack is intentionally a single-host MVP: the API and source-sync worker are separate processes, but both mount the same durable SQLite volume. Public TLS terminates in an owned reverse proxy/load balancer in front of `127.0.0.1:8000`; the Android release build must point only at that HTTPS origin.

## Versioned release smoke checklist (`release-checklist-v1`)

Automated in-process smoke is `python scripts/run_release_smoke.py` from `backend/` (fresh DB → health/ready → session → seeded load profile → feed → reopen). Do not treat a green script as the whole #169 gate: keep the saved load profile, top-3 bottleneck remediations, and before/after timings with the release notes.

Current remediations recorded by seeded-load-v3:

- idx_feed_items_user_dismissed
- atched_claim_knowledge_ids
- defer_feedback_ranking_until_user_batch
- incremental_knowledge_identity_attach
- canonicalize_text_lru_cache
- same_source_distinct_event_short_circuit
- skip_revision_judge_on_different_target

Before/after timings for the matched 12-incident corpus are under 	ests/gold/seeded_load/v01/. Regenerate with python scripts/run_seeded_load_profile.py.

## One-command start

From a clean host that has only this repository, Docker, and a filled `.env.release` (copy `.env.release.example`; never commit secrets):

```text
python scripts/start_release_stack.py --env-file .env.release --compose-file compose.release.yml
```

The script fail-closes on missing/placeholder GitHub OAuth values, an invalid Fernet token key, or a developer-default database path, then runs `docker compose -f compose.release.yml --env-file .env.release up -d --build`. Validate without starting containers with `--validate-only`.

Do not depend on a developer laptop's existing `data/bulletfeed.db`. The release database path inside the stack is `/data/bulletfeed.db` on the durable `bulletfeed-data` volume.

## Recovery and adversarial suite

Repeatable automation is `python scripts/run_recovery_security_suite.py` from `backend/`. It covers backup/snapshot restore identity, Observation→Claim lineage after restore, duplicate-delivery idempotency, idempotent `initialize()`, tenant-isolated Feed, replay recovery, and SSRF/private-address suites. `python scripts/run_process_recovery_drill.py` separately starts the API and worker as independent processes, kills and restarts each one, verifies readiness transitions, and confirms the session survives both restarts. Disk-full and partial-filesystem-write drills remain host-specific. Do not widen Bandit/Semgrep waivers to make these suites green.

## Required services

Run `docker compose -f compose.release.yml up -d api worker`. Both services use `.env.release` and the `bulletfeed-data` volume. `Database.initialize()` is the idempotent schema/migration entry point for both processes, so a newly deployed image upgrades the shared database before serving work.

`GET /health` is liveness/configuration information. `GET /health/ready` is the deployment readiness gate: the database must answer and the source-sync worker heartbeat must be fresh. The worker process runs `python -m app.release_worker`, writes a heartbeat every loop, and continues to use the existing leased/retryable source jobs.

The stack binds Uvicorn only to host loopback. Do not expose port 8000 directly to the internet. The public reverse proxy must provide HTTPS, forward the original scheme/host, set normal request-size/time limits, and route the configured HTTPS GitHub callback URL to the API container.

## Crawler identity

Public watches (generic web, RSS/JSON feeds, Statuspage) send `BULLETFEED_CRAWLER_USER_AGENT`. The release default is `BulletFeed/1.0 (+https://github.com/wogikaze/BulletFeed-fork; source-watch)`. Robots.txt evaluation and the page fetch use the same string. Empty or control-character values fail settings validation at startup. Tests should pass an explicit fixture UA when they care about the header.

## Secrets and storage

Create `.env.release` from `.env.release.example`. The GitHub client secret and `BULLETFEED_TOKEN_ENCRYPTION_KEY` are secrets and must come from the deployment secret manager rather than source control. The encryption key must remain stable across restarts or existing encrypted GitHub credentials cannot be read.

`bulletfeed-data` is stateful and must live on durable storage with host-level encryption and restricted access. Private-repository evidence is represented only through normalized application records; source policies are registered in `source_policies`, and unregistered source kinds are rejected before entering `event_sources`.

## Backup and restore

Run `docker compose -f compose.release.yml --profile maintenance run --rm backup` from the host scheduler at least daily. The backup command uses SQLite's online backup API rather than copying the live database file. Store the resulting `bulletfeed-backups` volume off-host according to the retention policy. `BULLETFEED_BACKUP_RETENTION_DAYS` controls local pruning only; off-host retention is an infrastructure responsibility.

Restore by stopping `api` and `worker`, replacing `/data/bulletfeed.db` from a verified backup, starting the services, and waiting for `/health/ready` to return 200. Perform a restore drill before public release and periodically afterward.

Operator restore-identity snapshots are a separate durable volume, `bulletfeed-snapshots`. Record one with `docker compose -f compose.release.yml --profile maintenance run --rm snapshot`. Each run writes a SQLite copy plus `bulletfeed-<utc>.identity.json` containing source/snapshot SHA-256 and `schema_migrations` revisions. Restore is valid only when the restored file's SHA-256 matches `snapshot_sha256` and the revision set matches. Backups (`bulletfeed-backups`) remain the scheduled retention copies; snapshots are explicit restore-identity artifacts.

## Deploy and rollback

Before deployment, run backend quality/security CI and Android quality CI. Deploy the image, start worker and API, wait for readiness, then smoke-test session creation/recovery, GitHub OAuth callback, repository selection, Feed, Event evidence, Security Alert, pagination, and account deletion against the public HTTPS origin.

For rollback, stop both processes and deploy the previous image. If a schema/data rollback is required, restore the pre-deploy backup rather than attempting to reverse an in-place SQLite migration. Keep API and worker on the same application version.

## Operational alerts

Alert on `/health/ready` failures, repeated worker job failures, backup failures, storage exhaustion, 5xx rate, GitHub reauthorization rates, and database corruption/integrity-check failures. A stale worker heartbeat means the product is no longer a monitoring service even if the HTTP API is still alive, so it is a release-severity condition.

## Data lifecycle

GitHub disconnect removes user watches and the encrypted upstream credential when it is no longer referenced. Account deletion removes the user-scoped profile, topics, Feed state, feedback/knownness, follows, GitHub watches, security alerts, notifications and sessions. Source-policy metadata is versioned in the database. Any future raw-body retention store must consult `retain_raw` and `retention_days`; normalized evidence must not be treated as permission to redistribute source content.
