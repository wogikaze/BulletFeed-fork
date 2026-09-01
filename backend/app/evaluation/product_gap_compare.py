"""A/B/C comparison: chronological RSS, topic filter, current BulletFeed ranker."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from app.services.multiobjective_ranker import RankerCandidate, rank_candidates

Mode = Literal["chronological", "topic_filter", "bulletfeed"]


@dataclass(frozen=True)
class CompareItem:
    item_id: str
    published_at: str
    topic_key: str
    important_unknown: bool
    already_known: bool
    duplicate: bool
    useful: bool
    candidate: RankerCandidate


def _sort_chrono(items: Sequence[CompareItem]) -> list[CompareItem]:
    return sorted(items, key=lambda item: item.published_at, reverse=True)


def arrange(items: Sequence[CompareItem], mode: Mode, *, followed_topics: set[str]) -> list[str]:
    if mode == "chronological":
        return [item.item_id for item in _sort_chrono(items)]
    if mode == "topic_filter":
        filtered = [item for item in _sort_chrono(items) if item.topic_key in followed_topics]
        return [item.item_id for item in filtered]
    ranked = rank_candidates(tuple(item.candidate for item in items))
    return [item.item_id for item in ranked]


def metrics_for(order: Sequence[str], items: Sequence[CompareItem], *, k: int = 10) -> dict[str, Any]:
    by_id = {item.item_id: item for item in items}
    window = [by_id[item_id] for item_id in order[:k] if item_id in by_id]
    important_unknown = [item for item in items if item.important_unknown]
    cards_to_first = next(
        (index + 1 for index, item in enumerate(window) if item.important_unknown),
        None,
    )
    hidden_unknown = [
        item.item_id
        for item in important_unknown
        if item.item_id not in {row.item_id for row in window}
    ]
    return {
        "cards_to_first_important_unknown": cards_to_first,
        "useful_rate": (sum(1 for item in window if item.useful) / len(window)) if window else 0.0,
        "already_known_reshow_rate": (
            sum(1 for item in window if item.already_known) / len(window) if window else 0.0
        ),
        "important_unknown_miss_rate": (
            len(hidden_unknown) / len(important_unknown) if important_unknown else 0.0
        ),
        "duplicate_rate": (sum(1 for item in window if item.duplicate) / len(window)) if window else 0.0,
        "unknown_but_hidden": len(hidden_unknown),
    }


def compare_modes(
    items: Sequence[CompareItem],
    *,
    followed_topics: set[str],
    k: int = 10,
) -> dict[str, Any]:
    table = {}
    for mode in ("chronological", "topic_filter", "bulletfeed"):
        order = arrange(items, mode, followed_topics=followed_topics)
        table[mode] = {
            "order": order,
            "metrics": metrics_for(order, items, k=k),
        }
    return {
        "report_version": "product-gap-c5-compare-v1",
        "k": k,
        "modes": table,
        "lost_metrics_kept": True,
    }


def attach_source_coverage(table: dict[str, Any], *, g3: dict[str, Any] | None) -> dict[str, Any]:
    coverage = {
        "rss_subset_coverage": None if g3 is None else g3.get("rss_subset_coverage"),
        "breadth_superiority_pp": None if g3 is None else g3.get("breadth_superiority_pp"),
        "rss_only_universe_recall": None if g3 is None else g3.get("rss_only_universe_recall"),
        "bulletfeed_universe_recall": None if g3 is None else g3.get("bulletfeed_universe_recall"),
        "live_oracle_unmeasured": True if g3 is None else g3.get("live_oracle_unmeasured", True),
    }
    return {**table, "source_coverage": coverage}
