"""Capacity-vs-ordering metrics for the short display frame.

Does not read blind labels. Item-level IU@10 is recorded but is not the
optimization target when the frame is already saturated with IU items.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from app.evaluation.m2_validation_metrics import IMPORTANT_MIN
from app.evaluation.personalization_gold import PersonalizationGoldCorpus
from app.services.multiobjective_ranker import candidate_from_gold_item
from app.services.ranking_capacity import occupancy_kind

KS = (5, 10, 20)


def cards_to_first_important_unknown(
    ranking: Sequence[str],
    important_unknown: set[str],
) -> int | None:
    if not important_unknown:
        return None
    for index, item_id in enumerate(ranking, start=1):
        if item_id in important_unknown:
            return index
    return None


def occupancy_at_k(
    ranking: Sequence[str],
    *,
    products: Mapping[str, str],
    sources: Mapping[str, str],
    kinds: Mapping[str, str],
    k: int,
) -> dict[str, Any]:
    top = list(ranking[:k])
    product_counts = Counter(products.get(item_id, "") for item_id in top)
    source_counts = Counter(sources.get(item_id, "") for item_id in top)
    kind_counts = Counter(kinds.get(item_id, "") for item_id in top)
    product_counts.pop("", None)
    source_counts.pop("", None)
    kind_counts.pop("", None)
    return {
        "unique_products": len(product_counts),
        "unique_sources": len(source_counts),
        "unique_kinds": len(kind_counts),
        "max_product_share": max(product_counts.values(), default=0) / k if k else 0.0,
        "max_source_share": max(source_counts.values(), default=0) / k if k else 0.0,
        "products": dict(product_counts.most_common(8)),
        "sources": dict(sorted(source_counts.items())),
        "kinds": dict(sorted(kind_counts.items())),
    }


def classify_miss(
    *,
    position: int | None,
    k: int,
    item_product: str,
    item_source: str,
    item_kind: str,
    frame_products: Mapping[str, int],
    frame_sources: Mapping[str, int],
    frame_kinds: Mapping[str, int],
    frame_saturated_with_iu: bool,
) -> str:
    if position is not None and position <= k:
        return "in_frame"
    product_full = bool(item_product) and frame_products.get(item_product, 0) >= 1
    source_full = bool(item_source) and frame_sources.get(item_source, 0) >= k
    kind_full = bool(item_kind) and frame_kinds.get(item_kind, 0) >= k
    if frame_saturated_with_iu or product_full or source_full or kind_full:
        return "capacity_miss"
    return "ordering_miss"


def user_capacity_row(
    *,
    user_id: str,
    ranking: Sequence[str],
    important_unknown: set[str],
    products: Mapping[str, str],
    sources: Mapping[str, str],
    kinds: Mapping[str, str],
    freeze_ids: set[str],
    hidden_count: int,
) -> dict[str, Any]:
    by_k: dict[str, Any] = {}
    for k in KS:
        top = set(ranking[:k])
        iu_hits = len(top & important_unknown)
        iu_products = {products[item_id] for item_id in important_unknown if products.get(item_id)}
        top_iu_products = {
            products[item_id] for item_id in top if item_id in important_unknown and products.get(item_id)
        }
        occupancy = occupancy_at_k(
            ranking, products=products, sources=sources, kinds=kinds, k=k
        )
        freeze_hits = len(top & freeze_ids)
        taxonomy = Counter()
        positions = {item_id: index for index, item_id in enumerate(ranking, start=1)}
        frame_products = Counter(products.get(item_id, "") for item_id in ranking[:k])
        frame_sources = Counter(sources.get(item_id, "") for item_id in ranking[:k])
        frame_kinds = Counter(kinds.get(item_id, "") for item_id in ranking[:k])
        saturated = len(important_unknown) >= k and iu_hits == k
        for item_id in important_unknown:
            taxonomy[
                classify_miss(
                    position=positions.get(item_id),
                    k=k,
                    item_product=products.get(item_id, ""),
                    item_source=sources.get(item_id, ""),
                    item_kind=kinds.get(item_id, ""),
                    frame_products=frame_products,
                    frame_sources=frame_sources,
                    frame_kinds=frame_kinds,
                    frame_saturated_with_iu=saturated,
                )
            ] += 1
        by_k[f"at_{k}"] = {
            "important_unknown_recall": (iu_hits / len(important_unknown)) if important_unknown else 1.0,
            "product_iu_recall": (len(top_iu_products) / len(iu_products)) if iu_products else 1.0,
            "freeze_hits": freeze_hits,
            "taxonomy": dict(sorted(taxonomy.items())),
            **occupancy,
        }
    first_iu = cards_to_first_important_unknown(ranking, important_unknown)
    return {
        "user_id": user_id,
        "important_unknown_count": len(important_unknown),
        "cards_to_first_important_unknown": first_iu,
        "hidden_count": hidden_count,
        "metrics": by_k,
    }


def maps_for_user(
    corpus: PersonalizationGoldCorpus,
    user,
    item_metadata: Mapping[str, Any] | None = None,
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    items = corpus.item_by_id()
    products: dict[str, str] = {}
    sources: dict[str, str] = {}
    kinds: dict[str, str] = {}
    for judgment in corpus.judgments_for_user(user.user_id):
        item = items[judgment.item_id]
        candidate = candidate_from_gold_item(user, item)
        products[judgment.item_id] = item.product
        meta = item_metadata.get(judgment.item_id) if item_metadata else None
        sources[judgment.item_id] = (
            getattr(meta, "source_family", None) or item.source_family or candidate.source_type
        )
        kinds[judgment.item_id] = (
            getattr(meta, "information_type", None) or occupancy_kind(candidate)
        )
    return products, sources, kinds


def important_unknown_ids(
    corpus: PersonalizationGoldCorpus,
    user_id: str,
    known_before: Mapping[tuple[str, str], bool],
) -> set[str]:
    return {
        row.item_id
        for row in corpus.judgments_for_user(user_id)
        if row.should_surface
        and row.importance_to_user >= IMPORTANT_MIN
        and not known_before.get((user_id, row.item_id), False)
    }


def mean(values: Sequence[float]) -> float:
    return round(sum(values) / len(values), 6) if values else 0.0
