"""Run the Rec-12 short-session ranking benchmark and optionally gate regressions.

Pilot labels may set floors. Blind labels are evaluation-only and are never
used to choose ranking constants.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.evaluation.ranking_benchmark import (
    BENCHMARK_VERSION,
    evaluate_ranking_benchmark,
    load_baseline_report,
    load_ranking_gold,
    require_ranking_regression_gate,
    write_report,
)

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "tests" / "gold" / "personalization" / "v01"
BASELINE = ROOT / "tests" / "gold" / "ranking_benchmark" / "v01" / "pilot_baseline.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rec-12 ranking benchmark")
    parser.add_argument("--split", choices=("pilot", "blind"), default="pilot")
    parser.add_argument("--check", action="store_true", help="compare pilot report to checked-in baseline")
    parser.add_argument("--write-baseline", action="store_true", help="overwrite the pilot baseline report")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    if args.check and args.split != "pilot":
        print("regression check is pilot-only; blind labels stay evaluation-only", file=sys.stderr)
        return 2

    corpus = load_ranking_gold(GOLD)
    report = evaluate_ranking_benchmark(corpus, split=args.split)
    payload = report.as_dict()
    if args.output is not None:
        write_report(report, args.output)
    if args.write_baseline:
        if args.split != "pilot":
            print("baseline may only be written from the pilot split", file=sys.stderr)
            return 2
        write_report(report, BASELINE)
        print(f"wrote {BASELINE}")
    if args.check:
        baseline = load_baseline_report(BASELINE)
        require_ranking_regression_gate(report, baseline)
        print(
            f"{BENCHMARK_VERSION} pilot gate OK "
            f"P@5={report.at_5.precision_at_k:.3f} "
            f"NDCG@10={report.at_10.ndcg_at_k:.3f}"
        )
        return 0
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
