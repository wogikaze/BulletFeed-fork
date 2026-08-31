"""Measure Top-3 persona-family IU recall after identity remediation.

Uses production scoring only. Blind records are never loaded.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from app.evaluation.m2_validation_metrics import evaluate_m2_production_scoring
from app.evaluation.real_world_validation import load_real_world_validation_for_production_scoring
from app.services.relation import RELATION_FEATURE_VERSION

BACKEND = Path(__file__).resolve().parents[1]
CORPUS = BACKEND / "tests" / "gold" / "real_world_validation" / "v01"
BASELINE = CORPUS / "m2_readiness_report.json"
OUTPUT = BACKEND / "tests" / "gold" / "m6" / "v01" / "cluster_recall_after_identity.json"
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
    production = load_real_world_validation_for_production_scoring(CORPUS)
    metrics = evaluate_m2_production_scoring(production, bootstrap_replicates=1)
    families: dict[str, Any] = {}
    for family in FAMILIES:
        before = _at10(frozen["metrics"]["segments"]["persona_family"][family])
        after = _at10(metrics["segments"]["persona_family"][family])
        families[family] = {
            "before": before,
            "after": after,
            "iu_recall_at_10_delta": round(
                after["important_unknown_recall_at_10"]
                - before["important_unknown_recall_at_10"],
                6,
            ),
        }
    headline_before = frozen["metrics"]["headline"]["include_ambiguous"]["at_10"]
    headline_after = metrics["headline"]["include_ambiguous"]["at_10"]
    payload = {
        "report_version": "m6-cluster-recall-after-identity-v1",
        "label_source": "AI-silver",
        "human_gold": False,
        "blind_read": False,
        "blind_records_loaded": metrics["blind_records_loaded"],
        "relation_feature_version": RELATION_FEATURE_VERSION,
        "frozen_baseline": "tests/gold/real_world_validation/v01/m2_readiness_report.json",
        "repository_sha": os.environ.get("GITHUB_SHA"),
        "headline_at_10": {
            "before": {
                "precision_at_10": headline_before["precision_at_10"],
                "recall_at_10": headline_before["recall_at_10"],
                "important_unknown_recall_at_10": headline_before[
                    "important_unknown_recall_at_10"
                ],
            },
            "after": {
                "precision_at_10": headline_after["precision_at_10"],
                "recall_at_10": headline_after["recall_at_10"],
                "important_unknown_recall_at_10": headline_after[
                    "important_unknown_recall_at_10"
                ],
            },
        },
        "persona_families": families,
        "notes": [
            "This is full-cluster production scoring, not the 20-case freeze sample.",
            "Identity remediation is frozen; this measurement does not read blind labels.",
            "Do not run #171 one-shot blind until Top-3 production remediation is complete.",
            "Top-3 family IU@10 delta is 0.",
            "Remaining gap is ranking_priority_or_capacity among equal-rank registry events.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
