from __future__ import annotations

import argparse
import json
import tempfile
import time
from argparse import Namespace
from dataclasses import asdict, dataclass
from pathlib import Path

from scripts.benchmark_capacity import CapacityReport, run, threshold_failures


@dataclass(frozen=True)
class SweepPoint:
    observations: int
    elapsed_seconds: float
    report: CapacityReport
    threshold_failures: list[str]


@dataclass(frozen=True)
class SweepReport:
    requested_sizes: list[int]
    completed_sizes: list[int]
    first_boundary_observations: int | None
    points: list[SweepPoint]


def benchmark_point(directory: Path, observations: int) -> SweepPoint:
    database = directory / f"capacity-{observations}.db"
    args = Namespace(
        database=str(database),
        observations=observations,
        observation_batch=1_000,
        feed_events=100,
        users=20,
        sync_jobs=5_000,
        assert_thresholds=False,
        output=None,
    )
    started = time.perf_counter()
    report = run(args)
    elapsed = time.perf_counter() - started
    return SweepPoint(
        observations=observations,
        elapsed_seconds=round(elapsed, 3),
        report=report,
        threshold_failures=threshold_failures(report),
    )


def run_sweep(sizes: list[int], *, directory: Path, stop_on_boundary: bool) -> SweepReport:
    if not sizes or any(size <= 0 for size in sizes):
        raise SystemExit("all sweep sizes must be positive")
    points: list[SweepPoint] = []
    first_boundary: int | None = None
    for size in sizes:
        point = benchmark_point(directory, size)
        points.append(point)
        if point.threshold_failures and first_boundary is None:
            first_boundary = size
            if stop_on_boundary:
                break
    return SweepReport(
        requested_sizes=sizes,
        completed_sizes=[point.observations for point in points],
        first_boundary_observations=first_boundary,
        points=points,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Find the first measured SQLite capacity threshold breach")
    parser.add_argument("--sizes", type=int, nargs="+", default=[100_000, 250_000, 500_000])
    parser.add_argument("--directory")
    parser.add_argument("--stop-on-boundary", action="store_true")
    parser.add_argument("--require-boundary", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args()

    directory = (
        Path(args.directory)
        if args.directory
        else Path(tempfile.mkdtemp(prefix="bulletfeed-capacity-sweep-"))
    )
    directory.mkdir(parents=True, exist_ok=True)
    report = run_sweep(
        args.sizes,
        directory=directory,
        stop_on_boundary=args.stop_on_boundary,
    )
    payload = json.dumps(asdict(report), indent=2, sort_keys=True)
    print(payload)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    if args.require_boundary and report.first_boundary_observations is None:
        raise SystemExit("no actionable threshold boundary was found in the requested sweep")


if __name__ == "__main__":
    main()
