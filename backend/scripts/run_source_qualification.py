"""Run M3 recorded-live source inventory and deterministic replay checks."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.evaluation.source_qualification import (
    load_and_evaluate_source_qualification,
    qualification_release_violations,
    write_source_qualification_report,
)

CORPUS = Path(__file__).resolve().parents[1] / "tests" / "gold" / "real_world_validation" / "v01"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    report = load_and_evaluate_source_qualification(CORPUS)
    if args.output is not None:
        write_source_qualification_report(report, args.output)
    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    if args.check:
        violations = qualification_release_violations(report)
        if violations:
            print("M3 source qualification gate failed:", file=sys.stderr)
            print("\n".join(f"- {item}" for item in violations), file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
