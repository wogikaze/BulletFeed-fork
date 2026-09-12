from __future__ import annotations

import argparse
import json
import math
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from app.config import Settings
from app.database import Database
from app.db.projection_schema import ensure_projection_schema
from app.services.event_coreference import CoreferenceInput, EventCoreferenceEngine
from app.services.feed_projection import FeedProjector
from app.services.source_ingestion import NormalizedObservation, SourceIngestionPipeline
from app.stores.feed_store import FeedStore
from app.sync_worker import WatchSyncWorker


@dataclass(frozen=True)
class LatencySummary:
    samples: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float


@dataclass(frozen=True)
class CapacityReport:
    observations: int
    feed_events: int
    users: int
    sync_jobs: int
    db_bytes: int
    observation_ingest: LatencySummary
    observation_replay: LatencySummary
    coreference_candidates: LatencySummary
    feed_projection: LatencySummary
    cursor_pages: LatencySummary
    sync_claim: LatencySummary


DEFAULT_THRESHOLDS_MS = {
    "observation_ingest": 3_000.0,
    "observation_replay": 3_000.0,
    "coreference_candidates": 150.0,
    "feed_projection": 150.0,
    "cursor_pages": 200.0,
    "sync_claim": 250.0,
}


def _summary(samples: list[float]) -> LatencySummary:
    ordered = sorted(samples)
    if not ordered:
        return LatencySummary(0, 0.0, 0.0, 0.0, 0.0)

    def percentile(fraction: float) -> float:
        index = max(0, math.ceil(len(ordered) * fraction) - 1)
        return ordered[index]

    return LatencySummary(
        samples=len(ordered),
        p50_ms=round(percentile(0.50), 3),
        p95_ms=round(percentile(0.95), 3),
        p99_ms=round(percentile(0.99), 3),
        max_ms=round(ordered[-1], 3),
    )


def _timed(callable_) -> tuple[object, float]:
    started = time.perf_counter()
    value = callable_()
    return value, (time.perf_counter() - started) * 1000.0


def _observation_items(count: int) -> list[NormalizedObservation]:
    return [
        NormalizedObservation(
            source_type="json_feed",
            source_key="https://bench.example/feed.json",
            source_observation_id=f"item-{index}",
            payload={"id": index, "title": f"Benchmark item {index}", "revision": index % 3},
            original_url=f"https://bench.example/items/{index}",
            published_at="2026-09-12T00:00:00Z",
        )
        for index in range(count)
    ]


def benchmark_observations(
    database: Database,
    *,
    count: int,
    batch_size: int,
) -> tuple[LatencySummary, LatencySummary]:
    pipeline = SourceIngestionPipeline(database)
    items = _observation_items(count)
    ingest_samples: list[float] = []
    replay_samples: list[float] = []
    for start in range(0, count, batch_size):
        batch = items[start : start + batch_size]
        _, elapsed = _timed(
            lambda batch=batch: pipeline.ingest_many(batch, retrieved_at="2026-09-12T00:05:00Z")
        )
        ingest_samples.append(elapsed)
    for start in range(0, count, batch_size):
        batch = items[start : start + batch_size]
        _, elapsed = _timed(
            lambda batch=batch: pipeline.ingest_many(batch, retrieved_at="2026-09-12T00:06:00Z")
        )
        replay_samples.append(elapsed)
    return _summary(ingest_samples), _summary(replay_samples)


def seed_feed_workload(
    database: Database,
    *,
    event_count: int,
    user_count: int,
) -> tuple[list[str], list[str]]:
    ensure_projection_schema(database)
    event_ids = [f"bench_event_{index:06d}" for index in range(event_count)]
    user_ids = [f"bench_user_{index:04d}" for index in range(user_count)]
    with database.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        for user_index, user_id in enumerate(user_ids):
            connection.execute("INSERT INTO users (id, created_at) VALUES (?, 0)", (user_id,))
            connection.execute(
                """
                INSERT INTO topics (id, user_id, name, type, priority, sort_order, created_at)
                VALUES (?, ?, 'Kotlin', 'technology', 'normal', 0, 0)
                """,
                (f"bench_topic_{user_index}", user_id),
            )
        for index, event_id in enumerate(event_ids):
            observation_id = f"bench_obs_feed_{index:06d}"
            claim_id = f"bench_claim_{index:06d}"
            delta_id = f"bench_delta_{index:06d}"
            occurred_at = f"2026-09-12T00:{index % 60:02d}:00Z"
            connection.execute(
                """
                INSERT INTO observations (
                    id, source_type, source_key, source_observation_id, payload_hash,
                    payload_json, original_url, published_at, retrieved_at
                ) VALUES (?, 'rss_atom', 'https://bench.example/feed.xml', ?, ?, '{}', ?, ?, ?)
                """,
                (
                    observation_id,
                    f"feed-{index}",
                    f"hash-{index}",
                    f"https://bench.example/feed/{index}",
                    occurred_at,
                    occurred_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO ledger_events (
                    id, source_type, source_key, source_event_id, title, created_at
                ) VALUES (?, 'rss_atom', 'https://bench.example/feed.xml', ?, ?, ?)
                """,
                (event_id, f"feed-{index}", f"Kotlin benchmark event {index}", occurred_at),
            )
            connection.execute(
                """
                INSERT INTO state_claims (
                    id, event_id, observation_id, slot, value_text, detail_text,
                    valid_at, source_updated_at, revision_hint, observed_at
                ) VALUES (?, ?, ?, 'publication_state', 'published', ?, ?, ?, '', ?)
                """,
                (
                    claim_id,
                    event_id,
                    observation_id,
                    f"Kotlin benchmark detail {index}",
                    occurred_at,
                    occurred_at,
                    occurred_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO events (
                    id, title, summary, current_phase, current_summary,
                    current_since, current_confidence, updated_at
                ) VALUES (?, ?, ?, 'published', ?, ?, 'high', ?)
                """,
                (
                    event_id,
                    f"Kotlin benchmark event {index}",
                    f"Kotlin benchmark detail {index}",
                    f"Kotlin benchmark detail {index}",
                    occurred_at,
                    occurred_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO deltas (
                    id, event_id, type, summary, before_text, after_text, occurred_at, active
                ) VALUES (?, ?, 'new_fact', ?, '', 'published', ?, 1)
                """,
                (delta_id, event_id, f"Kotlin benchmark detail {index}", occurred_at),
            )
            connection.execute(
                "INSERT INTO delta_claim_map (delta_id, claim_id, event_id) VALUES (?, ?, ?)",
                (delta_id, claim_id, event_id),
            )
        connection.commit()
    return event_ids, user_ids


def benchmark_feed(
    database: Database,
    *,
    event_ids: list[str],
    user_ids: list[str],
) -> tuple[LatencySummary, LatencySummary]:
    projector = FeedProjector(database)
    projection_samples: list[float] = []
    for user_id in user_ids:
        for event_id in event_ids:
            _, elapsed = _timed(
                lambda user_id=user_id, event_id=event_id: projector.project_event_for_user(
                    user_id=user_id,
                    event_id=event_id,
                )
            )
            projection_samples.append(elapsed)

    store = FeedStore(database)
    cursor_samples: list[float] = []
    cursor: str | None = None
    while True:
        (items, next_cursor), elapsed = _timed(
            lambda cursor=cursor: store.list_feed(
                user_ids[0],
                relation=None,
                item_status=None,
                cursor=cursor,
                limit=50,
            )
        )
        cursor_samples.append(elapsed)
        if not items or next_cursor is None:
            break
        cursor = next_cursor
    return _summary(projection_samples), _summary(cursor_samples)


def seed_coreference_candidates(database: Database, *, count: int) -> None:
    with database.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute("SELECT COUNT(*) FROM ledger_events").fetchone()[0]
        for index in range(existing, count):
            connection.execute(
                """
                INSERT OR IGNORE INTO ledger_events (
                    id, source_type, source_key, source_event_id, title, created_at
                ) VALUES (?, 'rss_atom', ?, ?, ?, ?)
                """,
                (
                    f"bench_coref_{index:07d}",
                    f"https://source-{index % 100}.example/feed.xml",
                    f"coref-{index}",
                    f"Synthetic coreference event {index}",
                    f"2026-09-{1 + index % 12:02d}T00:00:00Z",
                ),
            )
        connection.commit()


def benchmark_coreference(database: Database, *, repetitions: int = 50) -> LatencySummary:
    engine = EventCoreferenceEngine(database)
    value = CoreferenceInput(
        source_type="rss_atom",
        source_key="https://source-1.example/feed.xml",
        source_event_id="incoming-benchmark",
        title="Synthetic coreference event incoming",
        subject="synthetic coreference",
        valid_at="2026-09-12T00:00:00Z",
    )
    samples = []
    for _ in range(repetitions):
        _, elapsed = _timed(lambda: engine.retrieve_candidates(value))
        samples.append(elapsed)
    return _summary(samples)


def seed_sync_jobs(database: Database, *, count: int) -> None:
    with database.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.executemany(
            """
            INSERT OR REPLACE INTO source_sync_jobs (
                source_type, source_key, next_run_at, lease_until, failure_count
            ) VALUES ('github_advisory', ?, 1, 0, 0)
            """,
            [(f"bench-{index}",) for index in range(count)],
        )
        connection.commit()


def benchmark_sync_claim(database: Database, *, count: int) -> LatencySummary:
    worker = WatchSyncWorker(Settings(), database, batch_size=100)
    samples: list[float] = []
    claimed = 0
    now = 10_000
    while claimed < count:
        jobs, elapsed = _timed(lambda: worker.claim_due(now=now, limit=100))
        jobs = list(jobs)
        samples.append(elapsed)
        if not jobs:
            break
        claimed += len(jobs)
    return _summary(samples)


def threshold_failures(report: CapacityReport) -> list[str]:
    failures = []
    for field, threshold in DEFAULT_THRESHOLDS_MS.items():
        summary = getattr(report, field)
        if summary.p95_ms > threshold:
            failures.append(f"{field}: p95={summary.p95_ms:.3f}ms > {threshold:.3f}ms")
    return failures


def _assert_thresholds(report: CapacityReport) -> None:
    failures = threshold_failures(report)
    if failures:
        raise SystemExit("performance thresholds failed: " + "; ".join(failures))


def run(args: argparse.Namespace) -> CapacityReport:
    if args.database:
        db_path = Path(args.database)
        db_path.unlink(missing_ok=True)
        db_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        temp_dir = Path(tempfile.mkdtemp(prefix="bulletfeed-bench-"))
        db_path = temp_dir / "capacity.db"
    database = Database(db_path)
    database.initialize()

    ingest, replay = benchmark_observations(
        database,
        count=args.observations,
        batch_size=args.observation_batch,
    )
    feed_events = min(args.feed_events, args.observations)
    event_ids, user_ids = seed_feed_workload(
        database,
        event_count=feed_events,
        user_count=args.users,
    )
    feed_projection, cursor_pages = benchmark_feed(
        database,
        event_ids=event_ids,
        user_ids=user_ids,
    )
    seed_coreference_candidates(database, count=args.observations)
    coreference = benchmark_coreference(database)
    seed_sync_jobs(database, count=args.sync_jobs)
    sync_claim = benchmark_sync_claim(database, count=args.sync_jobs)

    report = CapacityReport(
        observations=args.observations,
        feed_events=feed_events,
        users=args.users,
        sync_jobs=args.sync_jobs,
        db_bytes=db_path.stat().st_size,
        observation_ingest=ingest,
        observation_replay=replay,
        coreference_candidates=coreference,
        feed_projection=feed_projection,
        cursor_pages=cursor_pages,
        sync_claim=sync_claim,
    )
    if args.assert_thresholds:
        _assert_thresholds(report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="BulletFeed SQLite capacity baseline")
    parser.add_argument("--database")
    parser.add_argument("--observations", type=int, default=10_000)
    parser.add_argument("--observation-batch", type=int, default=1_000)
    parser.add_argument("--feed-events", type=int, default=100)
    parser.add_argument("--users", type=int, default=20)
    parser.add_argument("--sync-jobs", type=int, default=5_000)
    parser.add_argument("--assert-thresholds", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args()
    report = run(args)
    payload = json.dumps(asdict(report), indent=2, sort_keys=True)
    print(payload)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
