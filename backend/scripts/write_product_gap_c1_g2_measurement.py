"""Write a G2 measurement artifact from production discovery. Dev split only."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.evaluation.product_gap_c1 import load_g0_sources
from app.evaluation.product_gap_c1_gates import evaluate_g2
from app.services.source_discovery import SOURCE_DISCOVERY_VERSION

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GOLD = ROOT / "tests" / "gold" / "product_gap" / "c1" / "v2"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold-dir", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--split", choices=("dev",), default="dev")
    args = parser.parse_args(argv)
    freeze = json.loads((args.gold_dir / "g0_freeze.json").read_text(encoding="utf-8"))
    floors = {str(key): float(value) for key, value in freeze["metrics"].items()}
    sources = [row for row in load_g0_sources(args.gold_dir / "sources.json") if row.split == args.split]
    g2 = evaluate_g2(sources, floors=floors)
    artifact = {
        "artifact_version": "product-gap-c1-g2-measurement-v1",
        "dataset_version": freeze.get("dataset_version"),
        "path": "production_discovery",
        "production_version": SOURCE_DISCOVERY_VERSION,
        "sample_complete": True,
        "split": args.split,
        "gold_injected": bool(g2.get("gold_injected")),
        "metrics": {
            "primary_recall_at_20": g2.get("primary_recall_at_20"),
            "relevant_recall_at_50": g2.get("relevant_recall_at_50"),
            "precision_at_20": g2.get("precision_at_20"),
            "japanese_recall_at_50": g2.get("japanese_recall_at_50"),
            "blog_recall_at_50": g2.get("blog_recall_at_50"),
            "no_rss_recall_at_50": g2.get("no_rss_recall_at_50"),
        },
        "weak_primary_topics": g2.get("weak_primary_topics"),
        "topics": g2.get("topics"),
    }
    output = args.gold_dir / "measurements" / "g2_measurement.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "gold_injected": artifact["gold_injected"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
