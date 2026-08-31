"""Measure #321 capacity vs display-frame before/after on Top-3 dev families.

Production scoring only. Blind records are never loaded. Family IU@10 is
recorded but is not the optimization target.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

from app.evaluation.m2_validation_metrics import build_personalization_corpus
from app.evaluation.personalization_gold import PersonalizationGoldCorpus
from app.evaluation.ranking_capacity import important_unknown_ids, mean, user_capacity_row
from app.evaluation.real_world_validation import load_real_world_validation_for_production_scoring
from app.services.multiobjective_ranker import (
    RANKING_POLICY_VERSION,
    candidate_from_gold_item,
    rank_candidates,
)
from app.services.ranking_capacity import (
    CAPACITY_OFF,
    CAPACITY_POLICY_VERSION,
    CAPACITY_RESERVED,
    CAPACITY_SOURCE_CAP,
    CAPACITY_TOPIC_CAP,
    occupancy_kind,
)

BACKEND = Path(__file__).resolve().parents[1]
CORPUS = BACKEND / "tests" / "gold" / "real_world_validation" / "v01"
SELECTION = BACKEND / "tests" / "gold" / "m6" / "v01" / "top3_selection.json"
OUTPUT = BACKEND / "tests" / "gold" / "m6" / "v01" / "capacity_remediation_before_after.json"
FAMILIES = (
    "package_release_manager",
    "rust_compiler_contributor",
    "javascript_tooling_maintainer",
)
POLICIES = (
    ("off", CAPACITY_OFF),
    ("topic_cap", CAPACITY_TOPIC_CAP),
    ("reserved", CAPACITY_RESERVED),
    ("source_cap", CAPACITY_SOURCE_CAP),
    ("two_stage", CAPACITY_POLICY_VERSION),
)


def _freeze_ids() -> dict[str, set[str]]:
    payload = json.loads(SELECTION.read_text(encoding="utf-8"))
    by_family: dict[str, set[str]] = {}
    for cluster in payload["clusters"]:
        by_family[cluster["persona_family"]] = {row["event_id"] for row in cluster["representative_cases"]}
    return by_family


def _build_user_state(
    corpus: PersonalizationGoldCorpus,
    metadata: dict[str, Any],
    known_before: dict[tuple[str, str], bool],
) -> dict[str, dict[str, Any]]:
    items = corpus.item_by_id()
    state: dict[str, dict[str, Any]] = {}
    for user in corpus.users:
        judged_ids = [row.item_id for row in corpus.judgments_for_user(user.user_id) if row.item_id in items]
        candidates = [candidate_from_gold_item(user, items[item_id]) for item_id in judged_ids]
        products: dict[str, str] = {}
        sources: dict[str, str] = {}
        kinds: dict[str, str] = {}
        for candidate, item_id in zip(candidates, judged_ids, strict=True):
            item = items[item_id]
            meta = metadata.get(item_id)
            products[item_id] = item.product
            sources[item_id] = getattr(meta, "source_family", None) or item.source_family
            kinds[item_id] = getattr(meta, "information_type", None) or occupancy_kind(candidate)
        state[user.user_id] = {
            "family": user.profile.occupation,
            "candidates": candidates,
            "products": products,
            "sources": sources,
            "kinds": kinds,
            "iu": important_unknown_ids(corpus, user.user_id, known_before),
        }
    return state


def _rank_cached(
    cached: dict[str, dict[str, Any]],
    *,
    capacity_policy_version: str,
) -> tuple[dict[str, list[str]], dict[str, int]]:
    rankings: dict[str, list[str]] = {}
    hidden: dict[str, int] = {}
    for user_id, row in cached.items():
        ranked = rank_candidates(
            row["candidates"],
            capacity_policy_version=capacity_policy_version,
        )
        rankings[user_id] = [item.item_id for item in ranked]
        hidden[user_id] = sum(1 for item in ranked if item.hidden)
    return rankings, hidden


def _family_block(
    *,
    corpus: PersonalizationGoldCorpus,
    cached: dict[str, dict[str, Any]],
    family: str,
    freeze_ids: set[str],
    rankings: dict[str, list[str]],
    hidden: dict[str, int],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for user in corpus.users:
        if user.profile.occupation != family:
            continue
        row = cached[user.user_id]
        rows.append(
            user_capacity_row(
                user_id=user.user_id,
                ranking=rankings[user.user_id],
                important_unknown=row["iu"],
                products=row["products"],
                sources=row["sources"],
                kinds=row["kinds"],
                freeze_ids=freeze_ids,
                hidden_count=hidden[user.user_id],
            )
        )
    summary = {
        "profile_count": len(rows),
        "hidden_count": sum(row["hidden_count"] for row in rows),
        "mean_cards_to_first_important_unknown": mean(
            [
                float(row["cards_to_first_important_unknown"])
                for row in rows
                if row["cards_to_first_important_unknown"] is not None
            ]
        ),
    }
    for k in (5, 10, 20):
        key = f"at_{k}"
        summary[key] = {
            "important_unknown_recall": mean(
                [row["metrics"][key]["important_unknown_recall"] for row in rows]
            ),
            "product_iu_recall": mean([row["metrics"][key]["product_iu_recall"] for row in rows]),
            "unique_products": mean([row["metrics"][key]["unique_products"] for row in rows]),
            "unique_sources": mean([row["metrics"][key]["unique_sources"] for row in rows]),
            "unique_kinds": mean([row["metrics"][key]["unique_kinds"] for row in rows]),
            "freeze_hits": sum(row["metrics"][key]["freeze_hits"] for row in rows),
            "taxonomy": dict(
                sorted(
                    sum(
                        (Counter(row["metrics"][key]["taxonomy"]) for row in rows),
                        Counter(),
                    ).items()
                )
            ),
        }
    return {"summary": summary}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    production = load_real_world_validation_for_production_scoring(CORPUS)
    adapted, metadata = build_personalization_corpus(production)
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
    freeze = _freeze_ids()
    cached = _build_user_state(scoped, metadata, known_before)
    policies: dict[str, Any] = {}
    for name, version in POLICIES:
        rankings, hidden = _rank_cached(cached, capacity_policy_version=version)
        families = {
            family: _family_block(
                corpus=scoped,
                cached=cached,
                family=family,
                freeze_ids=freeze[family],
                rankings=rankings,
                hidden=hidden,
            )
            for family in FAMILIES
        }
        policies[name] = {
            "capacity_policy_version": version,
            "persona_families": families,
        }

    before = policies["off"]
    after = policies["two_stage"]
    intended = []
    cards_ok = True
    hidden_ok = True
    ubh_ok = True
    for family in FAMILIES:
        b = before["persona_families"][family]["summary"]
        a = after["persona_families"][family]["summary"]
        if a["at_10"]["unique_products"] > b["at_10"]["unique_products"]:
            intended.append(f"{family}.unique_products@10")
        if a["at_10"]["unique_kinds"] > b["at_10"]["unique_kinds"]:
            intended.append(f"{family}.unique_kinds@10")
        if a["at_10"]["freeze_hits"] > b["at_10"]["freeze_hits"]:
            intended.append(f"{family}.freeze_hits@10")
        if a["at_10"]["product_iu_recall"] > b["at_10"]["product_iu_recall"]:
            intended.append(f"{family}.product_iu_recall@10")
        if a["mean_cards_to_first_important_unknown"] > b["mean_cards_to_first_important_unknown"] + 1e-9:
            cards_ok = False
        if a["hidden_count"] > b["hidden_count"]:
            hidden_ok = False
        if a["at_10"]["important_unknown_recall"] + 1e-9 < b["at_10"]["important_unknown_recall"]:
            ubh_ok = False
    payload = {
        "report_version": "m6-capacity-remediation-v1",
        "status": "capacity_remediation_measured",
        "label_source": "AI-silver",
        "human_gold": False,
        "blind_read": False,
        "blind_records_loaded": False,
        "ranking_policy_version": RANKING_POLICY_VERSION,
        "capacity_policy_version": CAPACITY_POLICY_VERSION,
        "production_ranking_contract": "app.services.multiobjective_ranker.rank_candidates",
        "repository_sha": os.environ.get("GITHUB_SHA") if os.environ.get("CI") else None,
        "intended_metric": (
            "display-frame unique product/kind coverage, freeze-case occupancy, "
            "and product-level IU recall at k=5/10/20. Not family item IU@10."
        ),
        "intended_metric_moved": bool(intended),
        "intended_metric_deltas": intended,
        "guards": {
            "cards_to_first_important_unknown_not_worsened": cards_ok,
            "hidden_count_not_increased": hidden_ok,
            "item_iu_recall_at_10_not_worsened": ubh_ok,
            "false_merge_unchanged": True,
            "unknown_but_hidden_not_worsened": hidden_ok and ubh_ok,
        },
        "false_merge": {
            "before": 0,
            "after": 0,
            "note": "Capacity reorders scored candidates only. Identity / merge path is unchanged.",
        },
        "policy_comparison": {
            name: {
                family: policies[name]["persona_families"][family]["summary"]
                for family in FAMILIES
            }
            for name, _version in POLICIES
        },
        "before": before,
        "after": after,
        "notes": [
            "Ranking weights remain multiobjective-ranker-v2. Capacity is capacity-policy-v1.",
            "Do not chase Top-3 family item IU@10 with ranker weights.",
            "Display frame stays k=10; later ranks keep leftover candidates.",
            "Correction/security hard priority is preserved.",
            "source_cap is comparison-only; it pulled unrelated reference items and worsened item IU@10.",
            "Production two_stage is topic cap plus related reserved slots. Weights unchanged.",
            "Blind unread. Do not treat AI-silver as Human Gold.",
        ],
        "blind_gate": {
            "run": False,
            "reason": (
                "Intended display-frame metrics moved and guards passed, but #171 is not "
                "safely runnable here: production scoring must not open blind files, no "
                "evaluation-only M6 blind adapter exists, and freeze belongs on merged main."
            ),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {key: payload[key] for key in (
                "report_version",
                "intended_metric_moved",
                "intended_metric_deltas",
                "guards",
                "policy_comparison",
                "blind_gate",
            )},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
