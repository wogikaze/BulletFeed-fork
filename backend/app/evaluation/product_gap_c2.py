"""Persona-pair differentiation and adjacent-discovery scoring (#316 / #322)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from app.evaluation.product_gap_compare import CompareItem, arrange
from app.services.multiobjective_ranker import RankerCandidate
from app.services.user_interest import concept_neighbors, resolve_concept_id


@dataclass(frozen=True)
class PersonaPair:
    pair_id: str
    left_persona: str
    right_persona: str
    left_topics: tuple[str, ...]
    right_topics: tuple[str, ...]


def kendall_tau_distance(left: Sequence[str], right: Sequence[str]) -> float:
    shared = [item for item in left if item in set(right)]
    if len(shared) < 2:
        return 0.0
    index = {item: position for position, item in enumerate(right)}
    discordant = 0
    total = 0
    for i, first in enumerate(shared):
        for second in shared[i + 1 :]:
            total += 1
            if index[first] > index[second]:
                discordant += 1
    return discordant / total if total else 0.0


def personalization_insufficiency(distance: float, *, floor: float = 0.15) -> bool:
    return distance < floor


def _relation_level(topic_key: str, followed: set[str]) -> str:
    if topic_key in followed:
        return "direct"
    followed_ids = {resolve_concept_id(topic) for topic in followed}
    item_id = resolve_concept_id(topic_key)
    for topic in followed_ids:
        if item_id in concept_neighbors(topic) or topic in concept_neighbors(item_id):
            return "adjacent"
    return "reference"


def _items_for_topics(items: Sequence[CompareItem], topics: Sequence[str]) -> list[CompareItem]:
    followed = set(topics)
    rebuilt: list[CompareItem] = []
    for item in items:
        level = _relation_level(item.topic_key, followed)
        candidate = RankerCandidate(
            item_id=item.candidate.item_id,
            event_id=item.candidate.event_id,
            redundancy_group=item.candidate.redundancy_group,
            topic_key=item.topic_key,
            relation_level=level,
            importance_level=item.candidate.importance_level,
            knownness_state=item.candidate.knownness_state,
            updated_at=item.published_at,
        )
        rebuilt.append(replace(item, candidate=candidate))
    return rebuilt


def score_pair(
    items: Sequence[CompareItem],
    pair: PersonaPair,
) -> dict[str, object]:
    left = arrange(
        _items_for_topics(items, pair.left_topics),
        "bulletfeed",
        followed_topics=set(pair.left_topics),
    )
    right = arrange(
        _items_for_topics(items, pair.right_topics),
        "bulletfeed",
        followed_topics=set(pair.right_topics),
    )
    distance = kendall_tau_distance(left, right)
    return {
        "pair_id": pair.pair_id,
        "kendall_distance": distance,
        "insufficient": personalization_insufficiency(distance),
        "left_order": left,
        "right_order": right,
    }


def score_adjacent_case(case: dict[str, Any]) -> dict[str, Any]:
    predicted = _relation_level(str(case["item_topic"]), set(case["persona_topics"]))
    return {
        "case_id": case["case_id"],
        "predicted": predicted,
        "expected": case["expected_match"],
        "hit": predicted == case["expected_match"],
        "useful": case.get("useful"),
        "label_source": "constructed",
    }


def evaluate_c2(gold_dir: Path, compare_items: Sequence[CompareItem]) -> dict[str, Any]:
    pairs_payload = json.loads((gold_dir / "persona_pairs.json").read_text(encoding="utf-8"))
    adjacent_payload = json.loads((gold_dir / "adjacent_cases.json").read_text(encoding="utf-8"))
    pair_reports = [
        score_pair(
            compare_items,
            PersonaPair(
                pair_id=row["pair_id"],
                left_persona=row["left_persona"],
                right_persona=row["right_persona"],
                left_topics=tuple(row["left_topics"]),
                right_topics=tuple(row["right_topics"]),
            ),
        )
        for row in pairs_payload["pairs"]
    ]
    adjacent_reports = [score_adjacent_case(row) for row in adjacent_payload["cases"]]
    insufficient = [row["pair_id"] for row in pair_reports if row["insufficient"]]
    adjacent_hits = sum(1 for row in adjacent_reports if row["hit"])
    human_gold = bool(pairs_payload.get("human_gold")) and bool(adjacent_payload.get("human_gold"))
    failures = []
    if insufficient:
        failures.append("persona_order_insufficient")
    if adjacent_hits < len(adjacent_reports):
        failures.append("adjacent_constructed_miss")
    if not human_gold:
        failures.append("human_adjacent_sample_missing")
    return {
        "dataset_version": pairs_payload["dataset_version"],
        "label_source": "constructed",
        "human_gold": human_gold,
        "pairs": pair_reports,
        "adjacent": adjacent_reports,
        "adjacent_precision": adjacent_hits / len(adjacent_reports) if adjacent_reports else 0.0,
        "pass": not failures,
        "failures": failures,
    }
