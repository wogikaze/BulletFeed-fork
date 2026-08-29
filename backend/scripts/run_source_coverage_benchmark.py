"""Run the Source-09 coverage benchmark and optionally apply release floors.

Pilot may set floors. Blind labels stay evaluation-only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.evaluation.source_coverage import (
    BENCHMARK_VERSION,
    evaluate_source_coverage,
    load_source_coverage_gold,
    require_coverage_release_gate,
    write_report,
)

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "tests" / "gold" / "source_coverage" / "v01"
BASELINE = GOLD / "pilot_baseline.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Source-09 coverage benchmark")
    parser.add_argument("--split", choices=("pilot", "blind"), default="pilot")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--write-baseline", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    if args.check and args.split != "pilot":
        print("coverage floors are pilot-only; blind labels stay evaluation-only", file=sys.stderr)
        return 2

    corpus = load_source_coverage_gold(GOLD)
    report = evaluate_source_coverage(corpus, split=args.split)
    if args.output is not None:
        write_report(report, args.output)
    if args.write_baseline:
        if args.split != "pilot":
            print("baseline may only be written from the pilot split", file=sys.stderr)
            return 2
        write_report(report, BASELINE)
        print(f"wrote {BASELINE}")
    if args.check:
        require_coverage_release_gate(report)
        print(
            f"{BENCHMARK_VERSION} pilot gate OK "
            f"discovery={report.discovery_recall:.3f} "
            f"static_gap={report.static_coverage_gap_rate:.3f}"
        )
        return 0
    print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
