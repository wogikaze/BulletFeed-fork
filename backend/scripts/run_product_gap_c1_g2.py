"""Record G2 production discovery metrics without injecting Gold hosts."""

from __future__ import annotations

import json
from pathlib import Path

from app.evaluation.product_gap_c1 import load_g0_sources
from app.evaluation.product_gap_c1_gates import _load_floors, evaluate_g2

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "tests" / "gold" / "product_gap" / "c1"


def main() -> int:
    floors = _load_floors(GOLD / "v2")
    sources = load_g0_sources(GOLD / "v2" / "sources.json")
    report = evaluate_g2(sources, floors=floors)
    output = GOLD / "v2" / "measurements" / "g2_measurement_after_ja.json"
    payload = {
        "artifact_version": "product-gap-c1-g2-measurement-after-ja-v1",
        "dataset_version": "product-gap-c1-g0-v2",
        "path": "production_discovery",
        "gold_injected": report["gold_injected"],
        "passed": report["passed"],
        "metrics": {
            "primary_recall_at_20": report["primary_recall_at_20"],
            "relevant_recall_at_50": report["relevant_recall_at_50"],
            "precision_at_20": report["precision_at_20"],
            "japanese_recall_at_50": report["japanese_recall_at_50"],
            "blog_recall_at_50": report["blog_recall_at_50"],
            "no_rss_recall_at_50": report["no_rss_recall_at_50"],
            "weak_primary_topics": report["weak_primary_topics"],
        },
        "failures": report["failures"],
        "note": "PR #425 Japanese catalog connected. Floors are not lowered. Not Human Gold.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(output),
                **payload["metrics"],
                "gold_injected": payload["gold_injected"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
