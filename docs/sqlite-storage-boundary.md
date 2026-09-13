# SQLite storage boundary

This document defines how `BulletFeed-fork` measures the storage/topology boundary of its current SQLite backend. It is a capacity decision, not a review-score target.

## Current decision rule

Keep SQLite while the deployment remains a **single writable host** and the fork's own capacity/contension workflow stays inside the guardrails below. The imported benchmark exercises 100k, 250k, and 500k Observation-scale databases, then runs concurrent Feed reads, Observation writes, and sync-lease claims at 500k.

The original `wogikaze/BulletFeed` experiment reached 500k without a scale-latency threshold breach, but those numbers are only provenance for this port. They are **not** accepted as `BulletFeed-fork` support evidence. This fork must generate its own artifact with `.github/workflows/sqlite-boundary.yml` before claiming the same verified range.

## What is measured

`backend/scripts/benchmark_capacity.py` records p50/p95/p99/max for:

- Observation ingestion and idempotent replay;
- Event-coreference candidate retrieval;
- Feed projection;
- Feed cursor reads;
- sync-job lease claiming;
- physical SQLite file size.

`backend/scripts/benchmark_sqlite_concurrency.py` additionally records:

- concurrent Feed-read p99;
- concurrent Observation-write p99;
- concurrent sync-claim p99;
- SQLite `database locked` errors;
- physical DB growth versus logical live payload bytes (write amplification).

Machine-readable JSON is uploaded by the workflow so a future boundary change is evidence-backed rather than inferred from table counts alone.

## Hard operating guardrails

SQLite remains an approved topology only while all of these are true:

1. There is exactly **one writable application/worker host** for the database file.
2. The deployed workload remains within the latest fork-verified range, or a larger range has passed the same sweep.
3. Concurrent Feed read p99 is <= **250 ms**.
4. Concurrent Observation batch-write p99 is <= **500 ms**.
5. Concurrent sync-claim p99 is <= **100 ms**.
6. The contention benchmark observes **zero database-lock errors**.
7. Physical-growth/logical-payload write amplification is <= **30x** for the synthetic live-write workload.
8. Existing backup/restore, persistent-volume disk-full, and recovery drills continue to pass; capacity that breaks those operational gates is a migration trigger even if request latency is acceptable.

A one-off noisy sample is investigated rather than treated as an automatic migration. A hard topology violation (multiple writer hosts) or reproducible lock errors is immediate. A latency/write-amplification breach should be reproduced before committing to a storage migration.

## PostgreSQL / multi-host migration triggers

Move away from the single-file SQLite topology when any of the following becomes necessary or reproducibly true:

- more than one host/process group must independently own write traffic;
- lock errors appear under the supported workload;
- write p99 stays above 500 ms, Feed read p99 above 250 ms, or sync-claim p99 above 100 ms after query/index remediation;
- write amplification exceeds the guardrail and maintenance cannot recover it;
- the required data volume exceeds the continuously verified range and extending the sweep shows a threshold breach;
- backup, restore, failover, or availability requirements require an independently replicated database service.

Observation count alone is not a migration trigger.

## Migration strategy

A future migration must preserve the replay model rather than copying only the latest user-visible projection.

1. Introduce a storage-adapter boundary while SQLite remains authoritative. Keep IDs, ordering keys, policy versions, and decision metadata unchanged.
2. Take a consistent SQLite snapshot and bulk-copy immutable `observations` first. Verify counts, IDs, payload hashes, source keys, source observation IDs, and retrieval timestamps.
3. Copy canonical semantic state (`ledger_events`, Claims, relations/authority metadata, Event identity history) and then user-scoped state.
4. Rebuild derived Event/Delta/Feed projections from immutable inputs in the target database where practical; compare deterministic digests rather than trusting a blind table copy.
5. Run the fork's replay/recovery, private-access, knownness, ranking, source-validation, release-gate, and observability suites against the target adapter.
6. During cutover, stop new writes briefly, apply the final delta from SQLite, compare counts/digests, then switch the single writer to the target database.
7. Keep the frozen SQLite snapshot as rollback evidence. Never run uncontrolled dual-primary writes.

The target may be PostgreSQL or another transactional store, but immutable Observation evidence, deterministic replay, provenance, and tenant isolation remain authoritative.
