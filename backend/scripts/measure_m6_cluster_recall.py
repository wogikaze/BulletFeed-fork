"""Measure Top-3 persona-family IU recall with current production scoring.

Uses production scoring only. Blind records are never loaded.
Default output is a new artifact; identity and feed-order-v5 reports stay frozen.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from app.evaluation.m2_validation_metrics import evaluate_m2_production_scoring
from app.evaluation.real_world_validation import load_real_world_validation_for_production_scoring
from app.services.multiobjective_ranker import RANKING_POLICY_VERSION
from app.services.relation import RELATION_FEATURE_VERSION

BACKEND = Path(__file__).resolve().parents[1]
CORPUS = BACKEND / "tests" / "gold" / "real_world_validation" / "v01"
BASELINE = CORPUS / "m2_readiness_report.json"
V5 = BACKEND / "tests" / "gold" / "m6" / "v01" / "cluster_recall_after_feed_order_v5.json"
OUTPUT = BACKEND / "tests" / "gold" / "m6" / "v01" / "cluster_recall_after_production_ranker.json"
FAMILIES = (
    "package_release_manager",
    "rust_compiler_contributor",
    "javascript_tooling_maintainer",
)


def _at10(segment: dict[str, Any]) -> dict[str, Any]:
    row = segment["at_10"]
    return {
        "sample_count": row["sample_count"],
        "judgment_count": row["judgment_count"],
        "precision_at_10": row["precision_at_10"],
        "recall_at_10": row["recall_at_10"],
        "important_unknown_recall_at_10": row["important_unknown_recall_at_10"],
        "unknown_but_hidden_rate": row["unknown_but_hidden_rate"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    frozen = json.loads(BASELINE.read_text(encoding="utf-8"))
    v5 = json.loads(V5.read_text(encoding="utf-8")) if V5.is_file() else None
    production = load_real_world_validation_for_production_scoring(CORPUS)
    metrics = evaluate_m2_production_scoring(production, bootstrap_replicates=1)
    families: dict[str, Any] = {}
    moved: list[str] = []
    for family in FAMILIES:
        before = _at10(frozen["metrics"]["segments"]["persona_family"][family])
        after = _at10(metrics["segments"]["persona_family"][family])
        delta = round(
            after["important_unknown_recall_at_10"] - before["important_unknown_recall_at_10"],
            6,
        )
        if delta != 0.0:
            moved.append(family)
        families[family] = {
            "before": before,
            "after": after,
            "iu_recall_at_10_delta": delta,
        }
    headline_before = frozen["metrics"]["headline"]["include_ambiguous"]["at_10"]
    headline_after = metrics["headline"]["include_ambiguous"]["at_10"]
    notes = [
        "M2 production scoring uses GET /feed rank_candidates (topic occupancy).",
        "Rec-12 rank_user_items / feed-order-v5 is unchanged.",
        "This is full-cluster production scoring, not the 20-case freeze sample.",
        "Blind unread. Do not treat AI-silver as Human Gold.",
    ]
    if moved:
        notes.append("Top-3 families with IU@10 movement vs frozen baseline: " + ", ".join(moved))
        notes.append(
            "Do not run #171 unless javascript_tooling_maintainer IU@10 moved and production logic is frozen."
        )
    else:
        notes.append("Top-3 family IU@10 delta vs frozen baseline is 0.")
        notes.append(
            "Headline IU@10 may move because production occupancy/redundancy is now scored; "
            "do not revert to rank_user_items to recover the headline."
        )
        notes.append(
            "Do not run #171 one-shot blind until a Top-3 production remediation moves family IU@10."
        )
    payload = {
        "report_version": "m6-cluster-recall-after-production-ranker-v1",
        "label_source": "AI-silver",
        "human_gold": False,
        "blind_read": False,
        "blind_records_loaded": metrics["blind_records_loaded"],
        "relation_feature_version": RELATION_FEATURE_VERSION,
        "ranking_policy_version": RANKING_POLICY_VERSION,
        "production_ranking_contract": metrics["production_ranking_contract"],
        "frozen_baseline": "tests/gold/real_world_validation/v01/m2_readiness_report.json",
        "feed_order_v5_report": "tests/gold/m6/v01/cluster_recall_after_feed_order_v5.json",
        "repository_sha": os.environ.get("GITHUB_SHA") if os.environ.get("CI") else None,
        "headline_at_10": {
            "frozen_baseline": {
                "precision_at_10": headline_before["precision_at_10"],
                "recall_at_10": headline_before["recall_at_10"],
                "important_unknown_recall_at_10": headline_before[
                    "important_unknown_recall_at_10"
                ],
            },
            "after_feed_order_v5": (
                v5["headline_at_10"]["after_feed_order_v5"] if v5 is not None else None
            ),
            "after_production_ranker": {
                "precision_at_10": headline_after["precision_at_10"],
                "recall_at_10": headline_after["recall_at_10"],
                "important_unknown_recall_at_10": headline_after[
                    "important_unknown_recall_at_10"
                ],
            },
        },
        "persona_families": families,
        "notes": notes,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
