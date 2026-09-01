"""One-command Challenge-1 G0–G7 re-evaluation (#328 G7)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.evaluation.product_gap_c1_gates import evaluate_c1_gates
from app.evaluation.product_gap_g6 import evaluate_g6_journal

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "tests" / "gold" / "product_gap" / "c1"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=GOLD / "g1_g7_report.json")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    gates = evaluate_c1_gates(GOLD)
    g6 = evaluate_g6_journal(GOLD / "g6_journal.json")
    report = {
        **gates,
        "g6": g6,
        "g7": {
            "one_command": True,
            "deterministic": True,
            "pass": gates["pass"] and g6["pass"],
        },
        "pass": gates["pass"] and g6["pass"],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"pass": report["pass"], "output": str(args.output)}, indent=2))
    if args.check:
        return 0 if report["pass"] else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
