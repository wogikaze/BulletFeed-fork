#!/usr/bin/env python3
"""Pilot-only product release gate. Floor edits need a new version+reason."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.evaluation.product_release_gate import (
    evaluate_product_release_gate,
    load_product_release_floors,
    require_product_release_gate,
)

ROOT = Path(__file__).resolve().parents[1]
FLOORS = ROOT / "tests/gold/product_release/v01/floors.json"
E2E = ROOT / "tests/gold/e2e_unknown_recall/v01/pilot/cases.json"
KNOWNNESS = ROOT / "tests/gold/knownness/v01"
COVERAGE = ROOT / "tests/gold/source_coverage/v01"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    report = evaluate_product_release_gate(
        floors=load_product_release_floors(FLOORS),
        e2e_cases_path=E2E,
        knownness_dir=KNOWNNESS,
        coverage_dir=COVERAGE,
    )
    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    if args.check:
        require_product_release_gate(report)


if __name__ == "__main__":
    main()
