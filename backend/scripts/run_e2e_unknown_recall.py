#!/usr/bin/env python3
"""Pilot-only E2E unknown-recall gate. Blind labels stay evaluation-only."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.evaluation.e2e_unknown_recall import (
    evaluate_e2e_unknown_recall,
    load_e2e_cases,
    require_e2e_release_gate,
)

PILOT = Path(__file__).resolve().parents[1] / "tests/gold/e2e_unknown_recall/v01/pilot/cases.json"
BLIND = Path(__file__).resolve().parents[1] / "tests/gold/e2e_unknown_recall/v01/blind/cases.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=("pilot", "blind"), default="pilot")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    path = PILOT if args.split == "pilot" else BLIND
    report = evaluate_e2e_unknown_recall(load_e2e_cases(path))
    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    if args.check:
        require_e2e_release_gate(report)


if __name__ == "__main__":
    main()
