"""Measure Challenge-2 persona pairs and adjacent constructed cases."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.evaluation.product_gap_c2 import evaluate_c2

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "tests" / "gold" / "product_gap"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=GOLD / "c2" / "measurement.json")
    args = parser.parse_args(argv)
    report = evaluate_c2(GOLD / "c2")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"pass": report["pass"], "output": str(args.output)}, indent=2))
    return 0 if report["human_gold"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
