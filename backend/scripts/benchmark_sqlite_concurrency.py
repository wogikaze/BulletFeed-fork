from __future__ import annotations

import argparse
import json
import math
import sqlite3
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path

from app.config import Settings
from app.database import Database
from app.services.feed_projection import FeedProjector
from app.services.source_ingestion import NormalizedObservation, SourceIngestionPipeline
from app.stores.feed_store import FeedStore
from app.sync_worker import WatchSyncWorker
from scripts.benchmark_capacity import LatencySummary, seed_feed_workload, seed_sync_jobs


@dataclass(frozen=True)
class ConcurrencyReport:
    base_observations: int
    feed_reads: LatencySummary
    observation_writes: LatencySummary
    sync_claims: LatencySummary
    lock_errors: int
    db_bytes_before_writes: int
    db_bytes_after_writes: int
    db_growth_bytes: int
    logical_payload_bytes_written: int
    write_amplification_ratio: float
    total_seconds: float


def summarize(samples: list[float]) -> LatencySummary:
    ordered = sorted(samples)
    if not ordered:
        return LatencySummary(0, 0.0, 0.0, 0.0, 0.0)

    def percentile(fraction: float) -> float:
        index = max(0, math.ceil(len(ordered) * fraction) - 1)
        return round(ordered[index], 3)

    return LatencySummary(
        samples=len(ordered),
        p50_ms=percentile(0.50),
        p95_ms=percentile(0.95),
        p99_ms=percentile(0.99),
        max_ms=round(ordered[-1], 3),
    )


def timed(callable_) -> tuple[object, float]:
    started = time.perf_counter()
    value = callable_()
    return value, (time.perf_counter() - started) * 1000.0


def prefill_observations(database: Database, count: int) -> None:
    pipeline = SourceIngestionPipeline(database)
    for start in range(0, count, 1_000):
        batch = [
            NormalizedObservation(
                source_type="json_feed",
                source_key="https://concurrency.example/base.json",
                source_observation_id=f"base-{index}",
                payload={"id": index},
                original_url=f"https://concurrency.example/base/{index}",
                published_at="2026-09-13T00:00:00Z",
            )
            for index in range(start, min(start + 1_000, count))
        ]
        pipeline.ingest_many(batch, retrieved_at="2026-09-13T00:01:00Z")


def seed_feed(database: Database) -> str:
    event_ids, user_ids = seed_feed_workload(database, event_count=50, user_count=1)
    projector = FeedProjector(database)
    for event_id in event_ids:
        projector.project_event_for_user(user_id=user_ids[0], event_id=event_id)
    return user_ids[0]


def _logical_payload_bytes() -> int:
    return sum(
        len(
            json.dumps(
                {"batch": batch_index, "id": index},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        for batch_index in range(50)
        for index in range(100)
    )


def run_contention(database: Database, *, user_id: str, sync_jobs: int) -> ConcurrencyReport:
    seed_sync_jobs(database, count=sync_jobs)
    db_bytes_before_writes = database.path.stat().st_size
    barrier = threading.Barrier(3)
    lock_errors = 0
    lock_guard = threading.Lock()

    def record_lock_error() -> None:
        nonlocal lock_errors
        with lock_guard:
            lock_errors += 1

    def feed_reader() -> list[float]:
        store = FeedStore(database)
        samples: list[float] = []
        barrier.wait()
        for _ in range(100):
            try:
                _, elapsed = timed(
                    lambda: store.list_feed(
                        user_id,
                        relation=None,
                        item_status=None,
                        cursor=None,
                        limit=20,
                    )
                )
                samples.append(elapsed)
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                record_lock_error()
        return samples

    def observation_writer() -> list[float]:
        pipeline = SourceIngestionPipeline(database)
        samples: list[float] = []
        barrier.wait()
        for batch_index in range(50):
            batch = [
                NormalizedObservation(
                    source_type="json_feed",
                    source_key="https://concurrency.example/live.json",
                    source_observation_id=f"live-{batch_index}-{index}",
                    payload={"batch": batch_index, "id": index},
                    original_url=f"https://concurrency.example/live/{batch_index}/{index}",
                    published_at="2026-09-13T00:02:00Z",
                )
                for index in range(100)
            ]
            try:
                _, elapsed = timed(
                    lambda batch=batch: pipeline.ingest_many(
                        batch,
                        retrieved_at="2026-09-13T00:03:00Z",
                    )
                )
                samples.append(elapsed)
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                record_lock_error()
        return samples

    def sync_claimer() -> list[float]:
        worker = WatchSyncWorker(Settings(), database, batch_size=100)
        samples: list[float] = []
        barrier.wait()
        claimed = 0
        while claimed < sync_jobs:
            try:
                jobs, elapsed = timed(lambda: worker.claim_due(now=10_000, limit=100))
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                record_lock_error()
                continue
            jobs = list(jobs)
            samples.append(elapsed)
            if not jobs:
                break
            claimed += len(jobs)
        return samples

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=3) as executor:
        read_future = executor.submit(feed_reader)
        write_future = executor.submit(observation_writer)
        sync_future = executor.submit(sync_claimer)
        read_samples = read_future.result()
        write_samples = write_future.result()
        sync_samples = sync_future.result()
    db_bytes_after_writes = database.path.stat().st_size
    db_growth = max(0, db_bytes_after_writes - db_bytes_before_writes)
    logical_payload_bytes = _logical_payload_bytes()
    amplification = db_growth / logical_payload_bytes if logical_payload_bytes else 0.0
    return ConcurrencyReport(
        base_observations=0,
        feed_reads=summarize(read_samples),
        observation_writes=summarize(write_samples),
        sync_claims=summarize(sync_samples),
        lock_errors=lock_errors,
        db_bytes_before_writes=db_bytes_before_writes,
        db_bytes_after_writes=db_bytes_after_writes,
        db_growth_bytes=db_growth,
        logical_payload_bytes_written=logical_payload_bytes,
        write_amplification_ratio=round(amplification, 3),
        total_seconds=round(time.perf_counter() - started, 3),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure SQLite API/read and worker/write contention")
    parser.add_argument("--database")
    parser.add_argument("--observations", type=int, default=100_000)
    parser.add_argument("--sync-jobs", type=int, default=5_000)
    parser.add_argument("--output")
    parser.add_argument("--assert-safe", action="store_true")
    args = parser.parse_args()

    if args.database:
        path = Path(args.database)
        path.unlink(missing_ok=True)
        path.parent.mkdir(parents=True, exist_ok=True)
    else:
        path = Path(tempfile.mkdtemp(prefix="bulletfeed-contention-")) / "contention.db"
    database = Database(path)
    database.initialize()
    prefill_observations(database, args.observations)
    user_id = seed_feed(database)
    report = run_contention(database, user_id=user_id, sync_jobs=args.sync_jobs)
    report = ConcurrencyReport(
        base_observations=args.observations,
        feed_reads=report.feed_reads,
        observation_writes=report.observation_writes,
        sync_claims=report.sync_claims,
        lock_errors=report.lock_errors,
        db_bytes_before_writes=report.db_bytes_before_writes,
        db_bytes_after_writes=report.db_bytes_after_writes,
        db_growth_bytes=report.db_growth_bytes,
        logical_payload_bytes_written=report.logical_payload_bytes_written,
        write_amplification_ratio=report.write_amplification_ratio,
        total_seconds=report.total_seconds,
    )
    payload = json.dumps(asdict(report), indent=2, sort_keys=True)
    print(payload)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    if args.assert_safe:
        failures = []
        if report.lock_errors:
            failures.append(f"database locked errors={report.lock_errors}")
        if report.feed_reads.p99_ms > 250:
            failures.append(f"feed read p99={report.feed_reads.p99_ms}ms > 250ms")
        if report.observation_writes.p99_ms > 500:
            failures.append(f"observation write p99={report.observation_writes.p99_ms}ms > 500ms")
        if report.sync_claims.p99_ms > 100:
            failures.append(f"sync claim p99={report.sync_claims.p99_ms}ms > 100ms")
        if report.write_amplification_ratio > 30:
            failures.append(
                f"write amplification={report.write_amplification_ratio:.3f}x > 30x"
            )
        if failures:
            raise SystemExit("SQLite concurrency guard failed: " + "; ".join(failures))


if __name__ == "__main__":
    main()
