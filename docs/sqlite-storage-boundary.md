# SQLite storage boundary

This document defines how `BulletFeed-fork` measures the storage/topology boundary of its current SQLite backend. It is a capacity decision, not a review-score target.

## Current decision

Keep SQLite for the current **single writable host** deployment, but do **not** claim the original repository's 500k Observation-scale support range for this fork.

The first fork-native post-port measurement, GitHub Actions run `34727172861` on PR #470, found the first tested scale point (100k Observations) already above the imported scale-latency guardrails. This is a software/query-performance boundary in the current fork, not evidence that the SQLite engine itself cannot store 100k Observations.

The original `wogikaze/BulletFeed` experiment reached 500k without the same scale-latency breach. Those numbers remain provenance only. The fork has richer current coreference, relation/ranking and Feed projection paths, so source-repository performance claims are not portable support evidence.

Until those hot paths are optimized and remeasured, the fork must not advertise 100k+ Observation-scale latency support from this benchmark. Existing lower-volume deployment remains acceptable only while its production SLOs and the existing backup/recovery/disk-full drills stay green.

## Measured fork evidence

First measured boundary run: `34727172861` on PR #470, exact branch head `53d1bb72b1651b43d344457a6cb42a937f854647` (PR merge-ref execution).

At 100,000 Observations:

| Measure | p50 | p95 | p99 | max |
| --- | ---: | ---: | ---: | ---: |
| Observation ingest (1,000/item batch) | 1257.254 ms | 1312.919 ms | 1701.583 ms | 1757.293 ms |
| Idempotent replay | 765.125 ms | 787.192 ms | 796.930 ms | 798.020 ms |
| Coreference candidate retrieval | 459.943 ms | **466.758 ms** | 496.847 ms | 496.847 ms |
| Feed projection | 215.550 ms | **400.610 ms** | 417.431 ms | 444.952 ms |
| Feed cursor page | 63.171 ms | 68.389 ms | 68.389 ms | 68.389 ms |
| Sync lease claim | 2.966 ms | 3.740 ms | 4.962 ms | 4.962 ms |

Physical DB size was **82,558,976 bytes**. The first boundary is therefore **100k**, because the imported scale guards were breached by:

- coreference candidate retrieval p95: **466.758 ms > 150 ms**;
- Feed projection p95: **400.610 ms > 150 ms**.

The sweep intentionally stops at the first breach. It therefore does not waste CI time measuring 250k/500k and does not reinterpret a failure as a verified higher range.

The current workflow also runs the concurrent Feed-read / Observation-write / sync-lease workload at the detected boundary point and uploads `sqlite-contention.json`. That artifact is the machine-readable source of truth for lock errors, concurrent p50/p95/p99, DB growth and write amplification. The workflow validates that all required evidence fields are present; it does not weaken or silently raise thresholds merely to make the port pass.

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

Machine-readable JSON is uploaded by `.github/workflows/sqlite-boundary.yml`, so a future boundary change is evidence-backed rather than inferred from table counts alone.

## Operating guardrails

SQLite remains an approved topology only while all of these are true:

1. There is exactly **one writable application/worker host** for the database file.
2. The deployed workload remains within a fork-verified range and production latency/error SLOs remain satisfied. The current 100k benchmark point is **not** a verified passing range.
3. Concurrent Feed read p99 is <= **250 ms**.
4. Concurrent Observation batch-write p99 is <= **500 ms**.
5. Concurrent sync-claim p99 is <= **100 ms**.
6. The contention benchmark observes **zero database-lock errors**.
7. Physical-growth/logical-payload write amplification is <= **30x** for the synthetic live-write workload.
8. Existing backup/restore, persistent-volume disk-full, and recovery drills continue to pass; capacity that breaks those operational gates is a migration trigger even if request latency is acceptable.

A single noisy latency sample is investigated rather than treated as an automatic storage migration. A hard topology violation (multiple writer hosts) or reproducible lock errors is immediate. The current 100k result is actionable optimization evidence because two independent query/projection paths breach their p95 guards by a large margin.

## Next performance work before claiming 100k+

1. Profile `EventCoreferenceEngine.retrieve_candidates()` on the fork's current schema and reduce the bounded candidate scan/query cost without weakening tenant visibility or identity hard negatives.
2. Profile `FeedProjector.project_event_for_user()` with the current relation, knownness and ranking overlays; remove avoidable per-event/per-user query work while preserving deterministic replay.
3. Add calibration points below 100k (for example 10k/25k/50k) if an explicit currently-supported capacity number is needed.
4. Re-run the same 100k -> 250k -> 500k sweep after optimization. A larger support claim requires a passing artifact; it is never inherited from the source repository.

## PostgreSQL / multi-host migration triggers

Move away from the single-file SQLite topology when any of the following becomes necessary or reproducibly true:

- more than one host/process group must independently own write traffic;
- lock errors appear under the supported workload;
- write p99 stays above 500 ms, Feed read p99 above 250 ms, or sync-claim p99 above 100 ms after query/index remediation;
- write amplification exceeds the guardrail and maintenance cannot recover it;
- the required data volume exceeds the continuously verified range and optimization/remeasurement cannot restore the scale guards;
- backup, restore, failover, or availability requirements require an independently replicated database service.

Observation count alone is not a migration trigger. The 100k breach currently points first to application/query optimization because coreference and Feed projection are the failing paths.

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
