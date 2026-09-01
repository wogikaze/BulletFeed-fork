"""Emit the #325 A/B/C comparison table, including lost metrics."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.evaluation.product_gap_c1_gates import evaluate_c1_gates
from app.evaluation.product_gap_compare import (
    CompareItem,
    attach_source_coverage,
    compare_modes,
)
from app.services.multiobjective_ranker import RankerCandidate

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "tests" / "gold" / "product_gap"


def items_from_fixture() -> tuple[list[CompareItem], set[str], int]:
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
    return items, set(payload["followed_topics"]), int(payload["k"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=GOLD / "c5" / "compare_table.json")
    args = parser.parse_args(argv)
    items, followed, k = items_from_fixture()
    table = compare_modes(items, followed_topics=followed, k=k)
    g3 = evaluate_c1_gates(GOLD / "c1")["g3"]
    table = attach_source_coverage(table, g3=g3)
    field = json.loads((GOLD / "c5" / "field_journal.json").read_text(encoding="utf-8"))
    table["field"] = field
    table["human_gold"] = False
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(table, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "lost_metrics_kept": True}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
