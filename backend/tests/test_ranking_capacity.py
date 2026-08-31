from app.evaluation.ranking_capacity import cards_to_first_important_unknown, classify_miss
from app.services.knowledge_evidence import CONFIDENCE_HIGH, STATE_KNOWN, STATE_UNKNOWN
from app.services.multiobjective_ranker import (
    RANKING_POLICY_VERSION,
    RankerCandidate,
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


def _candidate(**overrides: object) -> RankerCandidate:
    base: dict[str, object] = dict(
        item_id="item",
        event_id="evt",
        redundancy_group="group",
        topic_key="topic",
        relation_level="adjacent",
        relation_score=0.4,
        personalization_rank=200,
        importance_level="medium",
        knownness_state=STATE_UNKNOWN,
        knownness_confidence="none",
        delta_type="new_fact",
        source_type="package_registry",
        updated_at="2026-08-20T00:00:00Z",
    )
    base.update(overrides)
    return RankerCandidate(**base)  # type: ignore[arg-type]


def test_capacity_policy_is_versioned_apart_from_ranker_weights() -> None:
    items = [_candidate(item_id="a", topic_key="chrono"), _candidate(item_id="b", topic_key="clap")]
    ranked = rank_candidates(items)
    assert RANKING_POLICY_VERSION == "multiobjective-ranker-v2"
    assert ranked[0].policy_version == RANKING_POLICY_VERSION
    assert ranked[0].capacity_policy_version == CAPACITY_POLICY_VERSION
    assert CAPACITY_POLICY_VERSION != RANKING_POLICY_VERSION


def test_topic_cap_promotes_a_second_product_before_repeats() -> None:
    items = [
        _candidate(item_id=f"chrono-{index}", topic_key="chrono", redundancy_group=f"c{index}")
        for index in range(4)
    ] + [
        _candidate(
            item_id="clap-1",
            topic_key="clap",
            redundancy_group="clap-1",
            relation_score=0.2,
            personalization_rank=50,
        )
    ]
    off = rank_candidates(items, capacity_policy_version=CAPACITY_OFF)
    capped = rank_candidates(items, capacity_policy_version=CAPACITY_TOPIC_CAP)
    off_ids = [row.item_id for row in off]
    cap_ids = [row.item_id for row in capped]
    assert cap_ids[1] == "clap-1"
    assert off_ids.index("clap-1") > cap_ids.index("clap-1")
    assert set(off_ids) == set(cap_ids)


def test_reserved_incident_slot_beats_same_source_saturation() -> None:
    releases = [
        _candidate(
            item_id=f"npm-{index}",
            topic_key=f"pkg-{index}",
            redundancy_group=f"npm-{index}",
            source_type="package_registry",
        )
        for index in range(10)
    ]
    incident = _candidate(
        item_id="npm-status",
        topic_key="npm",
        redundancy_group="status",
        source_type="statuspage",
        delta_type="state_update",
        relation_score=0.1,
        personalization_rank=10,
        updated_at="2026-08-01T00:00:00Z",
    )
    off = rank_candidates([*releases, incident], capacity_policy_version=CAPACITY_OFF)
    reserved = rank_candidates([*releases, incident], capacity_policy_version=CAPACITY_RESERVED)
    assert occupancy_kind(incident) == "incident"
    assert "npm-status" not in [row.item_id for row in off[:10]]
    assert "npm-status" in [row.item_id for row in reserved[:10]]


def test_reserved_direct_slots_surface_followed_packages() -> None:
    adjacent = [
        _candidate(
            item_id=f"adj-{index}",
            topic_key=f"adj-{index}",
            redundancy_group=f"adj-{index}",
            relation_level="adjacent",
            relation_score=0.5,
        )
        for index in range(10)
    ]
    followed = [
        _candidate(
            item_id="eslint",
            topic_key="eslint",
            redundancy_group="eslint",
            relation_level="direct",
            relation_score=0.2,
            personalization_rank=20,
            updated_at="2026-07-01T00:00:00Z",
        ),
        _candidate(
            item_id="prettier",
            topic_key="prettier",
            redundancy_group="prettier",
            relation_level="direct",
            relation_score=0.2,
            personalization_rank=10,
            updated_at="2026-07-01T00:00:00Z",
        ),
    ]
    reserved = rank_candidates([*adjacent, *followed], capacity_policy_version=CAPACITY_RESERVED)
    frame = [row.item_id for row in reserved[:10]]
    assert "eslint" in frame
    assert "prettier" in frame
    assert frame.index("eslint") < 3
    assert frame.index("prettier") < 3


def test_source_cap_admits_another_family_without_raising_k() -> None:
    registry = [
        _candidate(
            item_id=f"npm-{index}",
            topic_key=f"pkg-{index}",
            redundancy_group=f"npm-{index}",
            source_type="package_registry",
        )
        for index in range(10)
    ]
    rss = _candidate(
        item_id="blog-1",
        topic_key="toolchain",
        redundancy_group="blog-1",
        source_type="rss_atom",
        relation_score=0.1,
        personalization_rank=10,
        updated_at="2026-08-01T00:00:00Z",
    )
    off = rank_candidates([*registry, rss], capacity_policy_version=CAPACITY_OFF)
    sourced = rank_candidates([*registry, rss], capacity_policy_version=CAPACITY_SOURCE_CAP)
    production = rank_candidates([*registry, rss])
    assert "blog-1" not in [row.item_id for row in off[:10]]
    assert "blog-1" in [row.item_id for row in sourced[:10]]
    assert "blog-1" not in [row.item_id for row in production[:10]]
    assert len(sourced) == 11


def test_correction_stays_ahead_of_capacity_fill() -> None:
    correction = _candidate(
        item_id="fix",
        topic_key="react",
        redundancy_group="fix",
        delta_type="correction",
        relation_level="reference",
        impact_snapshot={
            "version": "impact-signals-v1",
            "signals": {
                "correction_or_conflict": {
                    "value": "correction",
                    "source_field": "delta_type",
                    "reason": "t",
                    "confidence": "high",
                }
            },
        },
    )
    flood = [
        _candidate(
            item_id=f"rel-{index}",
            topic_key=f"pkg-{index}",
            redundancy_group=f"rel-{index}",
            relation_level="direct",
        )
        for index in range(8)
    ]
    ranked = rank_candidates([*flood, correction])
    assert ranked[0].item_id == "fix"
    assert ranked[0].priority_rule == "correction"


def test_capacity_never_drops_or_hides_unknown_items() -> None:
    items = [
        _candidate(item_id=f"p-{index}", topic_key="same", redundancy_group=f"g-{index}")
        for index in range(6)
    ]
    ranked = rank_candidates(items)
    assert {row.item_id for row in ranked} == {item.item_id for item in items}
    assert all(row.hidden is False for row in ranked)
    hidden = rank_candidates(
        [
            _candidate(
                item_id="known-same",
                knownness_state=STATE_KNOWN,
                knownness_confidence=CONFIDENCE_HIGH,
                identity_label="same_target",
                identity_confidence=CONFIDENCE_HIGH,
            )
        ]
    )[0]
    assert hidden.hidden is True


def test_first_item_stays_first_so_cards_to_first_do_not_worsen() -> None:
    items = [
        _candidate(item_id=f"pkg-{index}", topic_key=f"pkg-{index}", redundancy_group=f"g{index}")
        for index in range(12)
    ]
    off = rank_candidates(items, capacity_policy_version=CAPACITY_OFF)
    on = rank_candidates(items)
    assert on[0].item_id == off[0].item_id


def test_capacity_miss_is_separated_from_ordering_miss() -> None:
    assert cards_to_first_important_unknown(["a", "b", "c"], {"c"}) == 3
    assert cards_to_first_important_unknown(["a", "b"], {"z"}) is None
    assert (
        classify_miss(
            position=12,
            k=10,
            item_product="chrono",
            item_source="package_registry",
            item_kind="release",
            frame_products={"chrono": 2},
            frame_sources={"package_registry": 10},
            frame_kinds={"release": 10},
            frame_saturated_with_iu=True,
        )
        == "capacity_miss"
    )
    assert (
        classify_miss(
            position=12,
            k=10,
            item_product="eslint",
            item_source="package_registry",
            item_kind="release",
            frame_products={"chrono": 1},
            frame_sources={"package_registry": 6, "statuspage": 4},
            frame_kinds={"release": 6, "incident": 4},
            frame_saturated_with_iu=False,
        )
        == "ordering_miss"
    )
