"""Explain measured M6 ranking failures without changing production policy."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from statistics import median
from typing import Any

from app.evaluation.m2_validation_metrics import build_personalization_corpus
from app.evaluation.ranking_benchmark import (
    interest_state_for,
    rank_user_items,
    score_item_axes,
)
from app.evaluation.real_world_validation import (
    load_real_world_validation_for_production_scoring,
)

BACKEND = Path(__file__).resolve().parents[1]
CORPUS = BACKEND / "tests" / "gold" / "real_world_validation" / "v01"
SELECTION = BACKEND / "tests" / "gold" / "m6" / "v01" / "top3_selection.json"
REPORT_VERSION = "m6-ranking-root-cause-v1"


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain an object")
    return payload


def _root_cause(axis_rows: list[dict[str, Any]]) -> str:
    relation_reference = sum(row["relation_level"] == "reference" for row in axis_rows)
    personalization_zero = sum(row["personalization_rank"] == 0 for row in axis_rows)
    if (
        relation_reference / len(axis_rows) >= 0.75
        and personalization_zero / len(axis_rows) >= 0.75
    ):
        return (
            "semantic_identity_gap: the production relation path does not recognize "
            "the profile's package/product identity in these cases"
        )
    if relation_reference:
        return (
            "mixed_relation_gap: some cases lose product identity before ranking while "
            "the remainder receive only adjacent priority"
        )
    return (
        "ranking_priority_or_capacity: the cases receive a non-reference relation signal "
        "but remain outside the top-10 ordering"
    )


def analyze(selection: dict[str, Any], corpus) -> dict[str, Any]:
    adapted, _ = build_personalization_corpus(corpus)
    users = adapted.user_by_id()
    items = adapted.item_by_id()
    rankings: dict[str, list[str]] = {}
    for user in adapted.users:
        rankings[user.user_id] = rank_user_items(
            user,
            [items[judgment.item_id] for judgment in adapted.judgments_for_user(user.user_id)],
        )

    clusters: list[dict[str, Any]] = []
    for cluster in selection["clusters"]:
        axis_rows: list[dict[str, Any]] = []
        for case in cluster["representative_cases"]:
            user = users[case["profile_id"]]
            item = items[case["event_id"]]
            axis = score_item_axes(user, item, interest_state_for(user))
            position = rankings[user.user_id].index(item.item_id) + 1
            axis_rows.append(
                {
                    "case_id": case["case_id"],
                    "profile_id": case["profile_id"],
                    "event_id": case["event_id"],
                    "ranking_position": position,
                    "relation_level": axis.relation_level,
                    "relation_rank": axis.relation_rank,
                    "personalization_rank": axis.personalization_rank,
                    "importance_level": axis.importance_level,
                    "importance_rank": axis.importance_rank,
                    "interest_score": axis.interest_score,
                }
            )
        relation_counts = Counter(row["relation_level"] for row in axis_rows)
        importance_counts = Counter(row["importance_level"] for row in axis_rows)
        clusters.append(
            {
                "persona_family": cluster["persona_family"],
                "failure": cluster["failure"],
                "failure_count": cluster["failure_count"],
                "representative_case_count": len(axis_rows),
                "axis_summary": {
                    "relation_levels": dict(sorted(relation_counts.items())),
                    "importance_levels": dict(sorted(importance_counts.items())),
                    "personalization_rank_zero_count": sum(
                        row["personalization_rank"] == 0 for row in axis_rows
                    ),
                    "ranking_position": {
                        "median": median(row["ranking_position"] for row in axis_rows),
                        "min": min(row["ranking_position"] for row in axis_rows),
                        "max": max(row["ranking_position"] for row in axis_rows),
                    },
                    "interest_score": {
                        "median": median(row["interest_score"] for row in axis_rows),
                        "min": min(row["interest_score"] for row in axis_rows),
                        "max": max(row["interest_score"] for row in axis_rows),
                    },
                },
                "root_cause_hypothesis": _root_cause(axis_rows),
                "responsible_code_paths": [
                    "backend/app/evaluation/ranking_benchmark.py:score_item_axes",
                    "backend/app/services/relation.py:evaluate_relation_from_state",
                    "backend/app/services/event_concepts.py",
                ],
                "representative_cases": axis_rows,
                "regression_plan": {
                    "freeze_case_ids": [row["case_id"] for row in axis_rows],
                    "compare_before_after": [
                        "important_unknown_recall_at_10",
                        "unknown_but_hidden_rate",
                        "precision_at_10",
                        "ndcg_at_10",
                    ],
                    "catastrophic_counters_must_not_increase": [
                        "false_merge",
                        "unknown_but_hidden",
                        "correction_miss",
                    ],
                },
            }
        )
    return {
        "report_version": REPORT_VERSION,
        "status": "analysis_only",
        "label_source": "AI-silver",
        "human_gold": False,
        "blind_read": False,
        "stage_attribution": "ranking",
        "selection_rule": selection["selection_rule"],
        "clusters": clusters,
        "boundary": (
            "This report identifies measured production-ranking paths but does not tune "
            "against blind labels or assert a product-semantic decision for broad profiles."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, default=SELECTION)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    selection = _load(args.selection)
    corpus = load_real_world_validation_for_production_scoring(CORPUS)
    report = analyze(selection, corpus)
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
