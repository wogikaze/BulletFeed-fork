from __future__ import annotations

from pathlib import Path

from app.evaluation.personalization_gold import evaluate_personalization, load_personalization_gold
from app.services.impact_signals import extract_impact_signals, features_for_ranking
from app.services.knowledge_evidence import CONFIDENCE_HIGH, STATE_KNOWN, STATE_PROBABLY_KNOWN, STATE_UNKNOWN
from app.services.multiobjective_ranker import (
    AXIS_NAMES,
    CURSOR_VERSION,
    RANKING_POLICY_VERSION,
    RankerCandidate,
    decide_visibility,
    decode_ranking_cursor,
    encode_ranking_cursor,
    gold_item_to_source_record,
    paginate_ranked,
    priority_rule_for,
    rank_candidates,
    rank_personalization_corpus,
    score_axes,
)

_V01 = Path(__file__).parent / "gold" / "personalization" / "v01"


def _candidate(**overrides: object) -> RankerCandidate:
    base = dict(
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
        source_type="rss_atom",
        updated_at="2026-08-20T00:00:00Z",
    )
    base.update(overrides)
    return RankerCandidate(**base)  # type: ignore[arg-type]


def _impact(*, severity: str | None = None, incident: str | None = None, correction: str | None = None):
    signals: dict[str, dict[str, object]] = {}
    if severity is not None:
        signals["security_severity"] = {
            "value": severity,
            "source_field": "severity",
            "reason": "t",
            "confidence": "high",
        }
    if incident is not None:
        signals["incident_impact"] = {
            "value": incident,
            "source_field": "impact",
            "reason": "t",
            "confidence": "high",
        }
    if correction is not None:
        signals["correction_or_conflict"] = {
            "value": correction,
            "source_field": "delta_type",
            "reason": "t",
            "confidence": "high",
        }
    return {"version": "impact-signals-v1", "signals": signals}


def test_same_relation_level_orders_by_semantic_score() -> None:
    weak = _candidate(
        item_id="weak",
        relation_level="adjacent",
        relation_score=0.21,
        personalization_rank=200,
        importance_level="medium",
        redundancy_group="g-weak",
    )
    strong = _candidate(
        item_id="strong",
        relation_level="adjacent",
        relation_score=0.84,
        personalization_rank=200,
        importance_level="medium",
        redundancy_group="g-strong",
    )
    first = rank_candidates([weak, strong])
    second = rank_candidates([strong, weak])
    assert [row.item_id for row in first] == ["strong", "weak"]
    assert [row.item_id for row in second] == ["strong", "weak"]
    assert first[0].axes.relevance > first[1].axes.relevance


def test_policy_version_is_reproducible() -> None:
    items = [
        _candidate(item_id="a", relation_level="direct", importance_level="low", redundancy_group="g1"),
        _candidate(item_id="b", relation_level="reference", importance_level="high", redundancy_group="g2"),
        _candidate(item_id="c", relation_level="adjacent", importance_level="medium", redundancy_group="g3"),
    ]
    first = rank_candidates(items)
    second = rank_candidates(list(reversed(items)))
    assert first[0].policy_version == RANKING_POLICY_VERSION
    assert [row.item_id for row in first] == [row.item_id for row in second]
    assert [row.sort_key for row in first] == [row.sort_key for row in second]


def test_each_axis_is_separately_observable() -> None:
    item = _candidate(
        relation_level="direct",
        importance_level="low",
        knownness_state=STATE_PROBABLY_KNOWN,
        impact_snapshot=_impact(severity="high"),
    )
    axes = score_axes(item)
    payload = axes.as_dict()
    assert set(payload) == set(AXIS_NAMES)
    assert payload["relevance"] > payload["importance"]
    assert 0.0 < payload["novelty"] < 1.0
    assert payload["redundancy_penalty"] == 0.0
    ranked = rank_candidates([item])[0]
    assert ranked.axes.relevance == axes.relevance
    assert ranked.axes.importance == axes.importance
    assert ranked.hidden is False


def test_relation_is_not_folded_into_impact() -> None:
    record = {
        "source_type": "github_release",
        "title": "SDK 1.2.3",
        "summary": "Patch release.",
        "tag_name": "v1.2.3",
    }
    polluted = {
        **record,
        "relation_level": "direct",
        "novelty": "high",
        "personalization_rank": 1000,
        "matched_topics": ["security"],
    }
    clean = features_for_ranking(extract_impact_signals(record))
    dirty = features_for_ranking(extract_impact_signals(polluted))
    assert clean == dirty
    related = _candidate(item_id="rel", relation_level="direct", impact_snapshot=clean)
    unrelated = _candidate(item_id="unrel", relation_level="reference", impact_snapshot=dirty)
    assert score_axes(related).importance == score_axes(unrelated).importance
    assert score_axes(related).relevance > score_axes(unrelated).relevance


def test_confident_same_target_known_item_can_hide() -> None:
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
    assert hidden.visibility == "hide"
    assert hidden.hidden is True
    assert hidden.suppression_version
    assert "same-target" in hidden.suppression_reason


def test_uncertain_knownness_does_not_hide() -> None:
    assert decide_visibility(knownness_state=STATE_PROBABLY_KNOWN, knownness_confidence="medium") == "demote"
    assert decide_visibility(knownness_state=STATE_UNKNOWN, knownness_confidence="low") == "show"
    known = decide_visibility(knownness_state=STATE_KNOWN, knownness_confidence=CONFIDENCE_HIGH)
    assert known != "hide"
    ranked = rank_candidates(
        [
            _candidate(
                item_id="uncertain", knownness_state=STATE_PROBABLY_KNOWN, knownness_confidence="medium"
            ),
            _candidate(item_id="fresh", knownness_state=STATE_UNKNOWN),
        ]
    )
    ids = {row.item_id for row in ranked}
    assert ids == {"uncertain", "fresh"}
    assert all(row.hidden is False for row in ranked)
    assert all(row.visibility != "hide" for row in ranked)
    by_id = {row.item_id: row for row in ranked}
    assert by_id["uncertain"].axes.novelty < by_id["fresh"].axes.novelty


def test_corrections_and_critical_security_have_priority_rules() -> None:
    correction = _candidate(
        item_id="fix",
        delta_type="correction",
        relation_level="reference",
        impact_snapshot=_impact(correction="correction"),
    )
    related_cve = _candidate(
        item_id="cve",
        source_type="osv",
        relation_level="direct",
        impact_snapshot=_impact(severity="critical"),
    )
    blog = _candidate(item_id="blog", relation_level="direct", importance_level="low")
    assert priority_rule_for(correction) == "correction"
    assert priority_rule_for(related_cve) == "critical_security"
    ranked = rank_candidates([blog, related_cve, correction])
    assert [row.item_id for row in ranked][:2] == ["fix", "cve"]
    assert ranked[0].priority_rule == "correction"
    assert ranked[1].priority_rule == "critical_security"


def test_near_duplicates_are_penalized_not_deleted() -> None:
    items = [
        _candidate(item_id=f"dup-{index}", redundancy_group="same-event", topic_key="react")
        for index in range(4)
    ]
    ranked = rank_candidates(items)
    assert {row.item_id for row in ranked} == {item.item_id for item in items}
    assert ranked[0].axes.redundancy_penalty == 0.0
    assert ranked[1].axes.redundancy_penalty > 0.0
    assert ranked[-1].axes.redundancy_penalty >= ranked[1].axes.redundancy_penalty


def test_diversification_prevents_one_topic_from_occupying_top_k() -> None:
    items = [
        _candidate(
            item_id=f"react-{index}",
            redundancy_group=f"react-{index}",
            topic_key="react",
            relation_level="direct",
        )
        for index in range(5)
    ] + [
        _candidate(
            item_id="k8s-1", redundancy_group="k8s-1", topic_key="kubernetes", relation_level="adjacent"
        )
    ]
    ranked = rank_candidates(items)
    top = [row.item_id for row in ranked[:4]]
    assert "k8s-1" in top
    react_in_top = sum(1 for item_id in top if item_id.startswith("react-"))
    assert react_in_top < 4


def test_relevance_beats_unrelated_global_importance() -> None:
    relevant_release = _candidate(
        item_id="my-release",
        relation_level="direct",
        importance_level="medium",
        redundancy_group="mine",
        topic_key="react",
    )
    global_cve = _candidate(
        item_id="other-cve",
        relation_level="reference",
        importance_level="high",
        source_type="osv",
        redundancy_group="other",
        topic_key="kubernetes",
        impact_snapshot=_impact(severity="critical"),
    )
    ranked = rank_candidates([global_cve, relevant_release])
    assert ranked[0].item_id == "my-release"
    assert score_axes(global_cve).importance > score_axes(relevant_release).importance
    assert score_axes(relevant_release).relevance > score_axes(global_cve).relevance
    assert priority_rule_for(global_cve) == "critical_security"
    assert ranked[0].priority_tier == 1


def test_pagination_cursor_is_stable_for_one_ranking_version() -> None:
    items = [_candidate(item_id=f"i{index}", redundancy_group=f"g{index}") for index in range(5)]
    ranked = rank_candidates(items)
    page1, cursor = paginate_ranked(ranked, cursor=None, limit=2)
    page2, _cursor2 = paginate_ranked(ranked, cursor=cursor, limit=2)
    assert [row.item_id for row in page1] == [row.item_id for row in ranked[:2]]
    assert [row.item_id for row in page2] == [row.item_id for row in ranked[2:4]]
    assert cursor
    last_id = decode_ranking_cursor(cursor)
    assert last_id == page1[-1].item_id
    replay = encode_ranking_cursor(page1[-1].item_id)
    assert replay == cursor
    assert CURSOR_VERSION in "v5"
    try:
        decode_ranking_cursor("not-a-cursor")
        raise AssertionError("expected obsolete cursor")
    except ValueError as exc:
        assert "obsolete ranking version" in str(exc)


def test_gold_evaluator_reports_precision_recall_ndcg_and_redundancy() -> None:
    corpus = load_personalization_gold(_V01).for_split("pilot")
    rankings = rank_personalization_corpus(corpus)
    at5 = evaluate_personalization(corpus, rankings, k=5, split="pilot")
    at10 = evaluate_personalization(corpus, rankings, k=10, split="pilot")
    m5 = at5.include_ambiguous
    m10 = at10.include_ambiguous
    assert at5.k == 5
    assert at10.k == 10
    assert 0.0 <= m5.precision_at_k <= 1.0
    assert 0.0 <= m5.recall_at_k <= 1.0
    assert 0.0 <= m10.ndcg_at_k <= 1.0
    assert 0.0 <= m10.redundancy_at_k <= 1.0
    assert m5.precision_at_k > 0
    assert m5.recall_at_k > 0
    assert m10.ndcg_at_k > 0
    naive = {user.user_id: list(rankings[user.user_id]) for user in corpus.users}
    # Ranker must not consult Gold labels when building candidates.
    user = next(user for user in corpus.users if user.products)
    item = corpus.item_by_id()[corpus.judgments_for_user(user.user_id)[0].item_id]
    record = gold_item_to_source_record(item)
    assert "relevance" not in record
    assert "importance_to_user" not in record
    assert "should_surface" not in record
    del naive


def test_gold_ranker_reduces_redundancy_versus_undiversified_order() -> None:
    corpus = load_personalization_gold(_V01).for_split("pilot")
    diversified = rank_personalization_corpus(corpus)
    items = corpus.item_by_id()
    undiversified: dict[str, list[str]] = {}
    for user in corpus.users:
        judged = [row.item_id for row in corpus.judgments_for_user(user.user_id)]
        scored = []
        for item_id in judged:
            item = items[item_id]
            axes = score_axes(
                _candidate(
                    item_id=item_id,
                    redundancy_group=item.redundancy_group,
                    topic_key=item.product,
                    relation_level="adjacent" if item.product in user.products else "reference",
                    importance_level="high" if item.kind == "advisory" else "medium",
                )
            )
            scored.append((axes.relevance + axes.importance, item_id))
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        undiversified[user.user_id] = [item_id for _score, item_id in scored]
    diverse = evaluate_personalization(corpus, diversified, k=10, split="pilot")
    packed = evaluate_personalization(corpus, undiversified, k=10, split="pilot")
    assert diverse.include_ambiguous.redundancy_at_k <= packed.include_ambiguous.redundancy_at_k
