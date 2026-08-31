"""Record why Top-3 family IU@10 does not move at k=10.

Production scoring only. Blind records are never loaded.
Empty important-unknown sets use the existing metric contract (recall 1.0).
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from app.evaluation.m2_validation_metrics import IMPORTANT_MIN, build_personalization_corpus
from app.evaluation.personalization_gold import PersonalizationGoldCorpus
from app.evaluation.real_world_validation import load_real_world_validation_for_production_scoring
from app.services.multiobjective_ranker import (
    RANKING_POLICY_VERSION,
    candidate_from_gold_item,
    rank_personalization_corpus,
)

BACKEND = Path(__file__).resolve().parents[1]
CORPUS = BACKEND / "tests" / "gold" / "real_world_validation" / "v01"
OUTPUT = BACKEND / "tests" / "gold" / "m6" / "v01" / "top3_capacity_diagnosis.json"
FAMILIES = (
    "package_release_manager",
    "rust_compiler_contributor",
    "javascript_tooling_maintainer",
)
K = 10


def _user_row(
    *,
    user_id: str,
    cohort: str,
    judgment_count: int,
    iu_count: int,
    top_iu: int,
    top_useful: int,
    top_relation: dict[str, int],
) -> dict[str, Any]:
    precision = top_useful / K
    iu_recall = (top_iu / iu_count) if iu_count else 1.0
    saturated = iu_count >= K and top_iu == K and precision == 1.0
    vacuous = iu_count == 0
    return {
        "user_id": user_id,
        "cohort": cohort,
        "judgment_count": judgment_count,
        "important_unknown_count": iu_count,
        "top10_important_unknown": top_iu,
        "top10_useful": top_useful,
        "precision_at_10": precision,
        "important_unknown_recall_at_10": iu_recall,
        "vacuous_perfect_recall": vacuous,
        "k10_saturated": saturated,
        "top10_relation": top_relation,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    production = load_real_world_validation_for_production_scoring(CORPUS)
    adapted, _metadata = build_personalization_corpus(production)
    known_before = {(row.profile_id, row.event_id): row.known_before for row in production.judgments}
    family_users = tuple(user for user in adapted.users if user.profile.occupation in FAMILIES)
    family_ids = {user.user_id for user in family_users}
    scoped = PersonalizationGoldCorpus(
        dataset_version=adapted.dataset_version,
        label_protocol_version=adapted.label_protocol_version,
        users=family_users,
        items=adapted.items,
        judgments=tuple(row for row in adapted.judgments if row.user_id in family_ids),
    )
    rankings = rank_personalization_corpus(scoped)
    items = scoped.item_by_id()
    families: dict[str, Any] = {}
    for family in FAMILIES:
        rows: list[dict[str, Any]] = []
        for user in scoped.users:
            if user.profile.occupation != family:
                continue
            judged = list(scoped.judgments_for_user(user.user_id))
            by_item = {row.item_id: row for row in judged}
            iu = {
                row.item_id
                for row in judged
                if row.should_surface
                and row.importance_to_user >= IMPORTANT_MIN
                and not known_before.get((user.user_id, row.item_id), False)
            }
            top = rankings[user.user_id][:K]
            relation: dict[str, int] = {}
            top_iu = 0
            top_useful = 0
            for item_id in top:
                judgment = by_item[item_id]
                candidate = candidate_from_gold_item(user, items[item_id])
                relation[candidate.relation_level] = relation.get(candidate.relation_level, 0) + 1
                if item_id in iu:
                    top_iu += 1
                if judgment.should_surface:
                    top_useful += 1
            rows.append(
                _user_row(
                    user_id=user.user_id,
                    cohort=user.kind,
                    judgment_count=len(judged),
                    iu_count=len(iu),
                    top_iu=top_iu,
                    top_useful=top_useful,
                    top_relation=dict(sorted(relation.items())),
                )
            )
        mean_iu = round(sum(row["important_unknown_recall_at_10"] for row in rows) / len(rows), 6)
        families[family] = {
            "profile_count": len(rows),
            "vacuous_perfect_recall_profiles": sum(row["vacuous_perfect_recall"] for row in rows),
            "k10_saturated_profiles": sum(row["k10_saturated"] for row in rows),
            "mean_important_unknown_recall_at_10": mean_iu,
            "profiles": rows,
        }
    payload = {
        "report_version": "m6-top3-capacity-diagnosis-v1",
        "label_source": "AI-silver",
        "human_gold": False,
        "blind_read": False,
        "k": K,
        "ranking_policy_version": RANKING_POLICY_VERSION,
        "repository_sha": os.environ.get("GITHUB_SHA") if os.environ.get("CI") else None,
        "persona_families": families,
        "notes": [
            "IU recall for a user with zero important-unknown judgments is 1.0 (existing metric contract).",
            "Users with P@10=1.0 and IU count >> k are saturated at k=10; ranking order cannot raise IU@10.",
            "javascript family mean mixes saturated pilot users with vacuous-perfect dev users.",
            "Identity, recency, and production occupancy did not move Top-3 family IU@10.",
            "Do not run #171 to chase Top-3 family IU@10.",
            "Do not revert rank_user_items to hide headline movement.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
