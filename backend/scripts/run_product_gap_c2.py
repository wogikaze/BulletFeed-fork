"""Measure Challenge-2 persona pairs and adjacent constructed cases."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.evaluation.product_gap_c2 import evaluate_c2
from app.evaluation.product_gap_compare import CompareItem
from app.services.multiobjective_ranker import RankerCandidate

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "tests" / "gold" / "product_gap"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=GOLD / "c2" / "measurement.json")
    args = parser.parse_args(argv)
    payload = json.loads((GOLD / "c5" / "compare_fixture.json").read_text(encoding="utf-8"))
    items = [
        CompareItem(
            item_id=row["item_id"],
            published_at=row["published_at"],
            topic_key=row["topic_key"],
            important_unknown=row["important_unknown"],
            already_known=row["already_known"],
            duplicate=row["duplicate"],
            useful=row["useful"],
            candidate=RankerCandidate(
                item_id=row["item_id"],
                topic_key=row["topic_key"],
                relation_level=row["relation_level"],
                importance_level=row["importance_level"],
                updated_at=row["published_at"],
            ),
        )
        for row in payload["items"]
    ]
    report = evaluate_c2(GOLD / "c2", items)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"pass": report["pass"], "output": str(args.output)}, indent=2))
    return 0 if report["human_gold"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
