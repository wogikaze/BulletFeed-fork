from app.evaluation.personalization_gold import (
    PersonalizationItem,
    PersonalizationUser,
    ProfileRecord,
)
from app.evaluation.ranking_benchmark import RANKING_CONTRACT_VERSION, rank_user_items


def _user() -> PersonalizationUser:
    return PersonalizationUser(
        user_id="u_pkg",
        split="pilot",
        kind="cold_start",
        profile=ProfileRecord(
            occupation="package_release_manager",
            interests=["crates.io", "packages"],
            region="en",
        ),
        topics=(),
        repositories=(),
        prior_feedback=(),
        products=(),
        adjacent_products=(),
        watches_security=False,
    )


def _crate(item_id: str, occurred_at: str | None) -> PersonalizationItem:
    return PersonalizationItem(
        item_id=item_id,
        split="pilot",
        title="chrono 0.4.38",
        summary="chrono 0.4.38 from crates",
        source_family="package_registry",
        publisher="crates registry / chrono",
        url="https://crates.io/api/v1/crates/chrono/0.4.38",
        product="chrono",
        kind="release",
        redundancy_group=item_id,
        tokens=("chrono", "crates"),
        lexical_traps_for=(),
        adjacent_products=(),
        ambiguous_for=(),
        occurred_at=occurred_at,
    )


def test_ranking_contract_is_feed_order_v5() -> None:
    assert RANKING_CONTRACT_VERSION == "feed-order-v5"


def test_source_grounded_recency_beats_lexicographic_item_id() -> None:
    older = _crate("z-old", "2020-01-01T00:00:00Z")
    newer = _crate("a-new", "2026-08-01T00:00:00Z")
    ranked = rank_user_items(_user(), [older, newer])
    assert ranked[0] == "a-new"
    assert ranked[1] == "z-old"


def test_missing_occurred_at_is_not_invented_and_sorts_after_dated() -> None:
    dated = _crate("a-dated", "2026-08-01T00:00:00Z")
    undated = _crate("z-undated", None)
    ranked = rank_user_items(_user(), [undated, dated])
    assert undated.occurred_at is None
    assert ranked[0] == "a-dated"
    assert ranked[1] == "z-undated"
