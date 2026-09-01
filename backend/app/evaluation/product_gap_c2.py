"""Persona-pair differentiation and adjacent-discovery scoring (#316 / #322)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from app.evaluation.product_gap_compare import CompareItem, arrange
from app.services.knowledge_evidence import STATE_KNOWN, STATE_UNKNOWN
from app.services.multiobjective_ranker import RankerCandidate
from app.services.user_interest import concept_neighbors, resolve_concept_id

M6_TAXONOMY_CLASS = "personalization_insufficiency"
M6_TAXONOMY_PATH = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "gold"
    / "m6"
    / "v01"
    / "failure_taxonomy_classes.json"
)
CONTRAST_FAMILIES = frozenset({"topic_match", "concept_adjacent"})


@dataclass(frozen=True)
class PersonaPair:
    pair_id: str
    left_persona: str
    right_persona: str
    left_topics: tuple[str, ...]
    right_topics: tuple[str, ...]
    family: str = "topic_match"
    history: str = "cold_start"
    left_known_item_ids: tuple[str, ...] = ()
    right_known_item_ids: tuple[str, ...] = ()
    expect_demoted_item_id: str | None = None


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


def _items_for_persona(
    items: Sequence[CompareItem],
    topics: Sequence[str],
    known_ids: Sequence[str],
) -> list[CompareItem]:
    followed = set(topics)
    known = set(known_ids)
    rebuilt: list[CompareItem] = []
    for item in items:
        level = _relation_level(item.topic_key, followed)
        is_known = item.item_id in known
        candidate = RankerCandidate(
            item_id=item.candidate.item_id,
            event_id=item.candidate.event_id,
            redundancy_group=item.candidate.redundancy_group,
            topic_key=item.topic_key,
            relation_level=level,
            importance_level=item.candidate.importance_level,
            knownness_state=STATE_KNOWN if is_known else STATE_UNKNOWN,
            updated_at=item.published_at,
        )
        rebuilt.append(
            replace(item, candidate=candidate, already_known=is_known or item.already_known)
        )
    return rebuilt


def load_compare_items(gold_dir: Path) -> list[CompareItem]:
    payload = json.loads((gold_dir / "compare_items.json").read_text(encoding="utf-8"))
    items: list[CompareItem] = []
    for row in payload["items"]:
        items.append(
            CompareItem(
                item_id=row["item_id"],
                published_at=row["published_at"],
                topic_key=row["topic_key"],
                important_unknown=bool(row["important_unknown"]),
                already_known=bool(row["already_known"]),
                duplicate=bool(row["duplicate"]),
                useful=bool(row["useful"]),
                everyone_important=bool(row.get("everyone_important")),
                candidate=RankerCandidate(
                    item_id=row["item_id"],
                    topic_key=row["topic_key"],
                    importance_level=row["importance_level"],
                    updated_at=row["published_at"],
                ),
            )
        )
    return items


def load_persona_pair(row: dict[str, Any]) -> PersonaPair:
    return PersonaPair(
        pair_id=row["pair_id"],
        left_persona=row["left_persona"],
        right_persona=row["right_persona"],
        left_topics=tuple(row["left_topics"]),
        right_topics=tuple(row["right_topics"]),
        family=str(row.get("family") or "topic_match"),
        history=str(row.get("history") or "cold_start"),
        left_known_item_ids=tuple(row.get("left_known_item_ids") or ()),
        right_known_item_ids=tuple(row.get("right_known_item_ids") or ()),
        expect_demoted_item_id=row.get("expect_demoted_item_id"),
    )


def score_pair(
    items: Sequence[CompareItem],
    pair: PersonaPair,
    *,
    k: int = 5,
) -> dict[str, object]:
    left = arrange(
        _items_for_persona(items, pair.left_topics, pair.left_known_item_ids),
        "bulletfeed",
        followed_topics=set(pair.left_topics),
    )
    right = arrange(
        _items_for_persona(items, pair.right_topics, pair.right_known_item_ids),
        "bulletfeed",
        followed_topics=set(pair.right_topics),
    )
    distance = kendall_tau_distance(left, right)
    everyone_ids = [item.item_id for item in items if item.everyone_important]
    everyone_dropped = [
        item_id
        for item_id in everyone_ids
        if item_id not in left[:k] or item_id not in right[:k]
    ]
    demoted = None
    if pair.expect_demoted_item_id:
        left_pos = left.index(pair.expect_demoted_item_id) if pair.expect_demoted_item_id in left else None
        right_pos = (
            right.index(pair.expect_demoted_item_id) if pair.expect_demoted_item_id in right else None
        )
        demoted = (
            left_pos is not None and right_pos is not None and right_pos > left_pos
        )
    insufficient = (
        personalization_insufficiency(distance) if pair.family in CONTRAST_FAMILIES else False
    )
    return {
        "pair_id": pair.pair_id,
        "family": pair.family,
        "history": pair.history,
        "kendall_distance": distance,
        "insufficient": insufficient,
        "known_item_demoted": demoted,
        "everyone_important_dropped": everyone_dropped,
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


def m6_taxonomy_lists_personalization_insufficiency(path: Path = M6_TAXONOMY_PATH) -> bool:
    payload = json.loads(path.read_text(encoding="utf-8"))
    classes = payload.get("independent_classes") or []
    return M6_TAXONOMY_CLASS in classes and payload.get(M6_TAXONOMY_CLASS, {}).get(
        "folded_into_ranking_bug"
    ) is False


def evaluate_c2(
    gold_dir: Path,
    compare_items: Sequence[CompareItem] | None = None,
) -> dict[str, Any]:
    pairs_payload = json.loads((gold_dir / "persona_pairs.json").read_text(encoding="utf-8"))
    adjacent_payload = json.loads((gold_dir / "adjacent_cases.json").read_text(encoding="utf-8"))
    items = list(compare_items) if compare_items is not None else load_compare_items(gold_dir)
    k = 5
    compare_payload = gold_dir / "compare_items.json"
    if compare_payload.is_file():
        k = int(json.loads(compare_payload.read_text(encoding="utf-8")).get("k") or 5)
    pair_reports = [score_pair(items, load_persona_pair(row), k=k) for row in pairs_payload["pairs"]]
    adjacent_reports = [score_adjacent_case(row) for row in adjacent_payload["cases"]]
    insufficient = [
        row["pair_id"]
        for row in pair_reports
        if row["family"] in CONTRAST_FAMILIES and row["insufficient"]
    ]
    knownness_miss = [
        row["pair_id"]
        for row in pair_reports
        if row["family"] == "knownness" and row["known_item_demoted"] is not True
    ]
    everyone_dropped = sorted(
        {
            item_id
            for row in pair_reports
            for item_id in row["everyone_important_dropped"]
        }
    )
    adjacent_hits = sum(1 for row in adjacent_reports if row["hit"])
    human_gold = bool(pairs_payload.get("human_gold")) and bool(adjacent_payload.get("human_gold"))
    taxonomy_ok = m6_taxonomy_lists_personalization_insufficiency()
    failures = []
    if insufficient:
        failures.append("persona_order_insufficient")
    if knownness_miss:
        failures.append("knownness_not_demoted")
    if everyone_dropped:
        failures.append("everyone_important_dropped")
    if adjacent_hits < len(adjacent_reports):
        failures.append("adjacent_constructed_miss")
    if not human_gold:
        failures.append("human_adjacent_sample_missing")
    if not taxonomy_ok:
        failures.append("m6_taxonomy_class_missing")
    return {
        "dataset_version": pairs_payload["dataset_version"],
        "label_source": "constructed",
        "human_gold": human_gold,
        "m6_taxonomy_class": M6_TAXONOMY_CLASS,
        "m6_taxonomy_independent": taxonomy_ok,
        "pairs": pair_reports,
        "adjacent": adjacent_reports,
        "adjacent_precision": adjacent_hits / len(adjacent_reports) if adjacent_reports else 0.0,
        "insufficient_pairs": insufficient,
        "knownness_miss_pairs": knownness_miss,
        "everyone_important_dropped": everyone_dropped,
        "pass": not failures,
        "failures": failures,
    }
