"""Calibrate Delta-06 thresholds on #66 gold. Pilot selects; blind evaluates."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.evaluation.delta_calibration import (
    BENCHMARK_VERSION,
    evaluate_calibration,
    load_calibration_gold,
    persist_selected_thresholds,
    require_calibration_release_gate,
    select_thresholds,
    write_report,
)

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "tests" / "gold" / "delta_adversarial" / "v01"
OUT_DIR = ROOT / "tests" / "gold" / "delta_calibration" / "v01"
BASELINE = OUT_DIR / "pilot_baseline.json"
THRESHOLDS = OUT_DIR / "thresholds.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Delta-06 threshold calibration")
    parser.add_argument("--split", choices=("pilot", "blind"), default="pilot")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--write-baseline", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    corpus = load_calibration_gold(GOLD)
    selected_policy, selected, accuracy_max = select_thresholds(corpus)
    report = evaluate_calibration(
        corpus,
        split=args.split,
        thresholds=selected_policy,
        selected=selected,
        accuracy_maximizer=accuracy_max,
    )
    if args.output is not None:
        write_report(report, args.output)
    if args.write_baseline:
        if args.split != "pilot":
            print("baseline may only be written from the pilot split", file=sys.stderr)
            return 2
        write_report(report, BASELINE)
        persist_selected_thresholds(selected_policy, THRESHOLDS)
        print(f"wrote {BASELINE} and {THRESHOLDS}")
    if args.check:
        require_calibration_release_gate(report)
        print(
            f"{BENCHMARK_VERSION} {args.split} gate OK "
            f"merge={report.false_merge_count} split={report.false_split_count} "
            f"cost={report.selected.cost:.2f} acc={report.selected.accuracy:.3f}"
        )
        return 0
    print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
