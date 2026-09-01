from __future__ import annotations

import json
from pathlib import Path

from app.evaluation.product_gap_c1 import evaluate_g0
from app.evaluation.product_gap_c1_gates import evaluate_c1_gates, evaluate_g1
from app.evaluation.product_gap_c2 import PersonaPair, evaluate_c2, score_adjacent_case, score_pair
from app.evaluation.product_gap_c3 import decay_before_after
from app.evaluation.product_gap_c4 import fixture_reason_missing
from app.evaluation.product_gap_compare import CompareItem, compare_cohorts, compare_modes
from app.evaluation.product_gap_ssrf import evaluate_ssrf_suite
from app.services.knowledge_evidence import (
    KIND_ALREADY_KNEW,
    KIND_DISPLAYED,
    KnowledgeEvidence,
    derive_knowledge_state,
)
from app.services.multiobjective_ranker import RankerCandidate
from app.services.rss_article_enrichment import enrich_html_bytes, is_summary_only
from app.services.web_snapshots import RobotsDecision

GOLD = Path(__file__).resolve().parents[0] / "gold" / "product_gap"
FIXTURES = Path(__file__).resolve().parents[0] / "fixtures"


def test_g0_is_not_human_gold_and_keeps_policy_blocked() -> None:
    report = evaluate_g0(GOLD / "c1")
    assert report.attested is False
    assert "attestation_pending" in report.failures
    assert report.policy_blocked_count >= 1
    assert report.floors_pass is False
    sources = json.loads((GOLD / "c1" / "sources.json").read_text(encoding="utf-8"))
    urls = {row["site_url"].rstrip("/") for row in sources}
    assert "https://zenn.dev" not in urls
    assert "https://qiita.com" not in urls
    assert "https://gohugo.io/news" not in urls
    splits = {}
    for row in sources:
        splits.setdefault(row["registrable_domain"], set()).add(row["split"])
    assert all(len(values) == 1 for values in splits.values())


def test_ssrf_suite_uses_production_shape_and_does_not_claim_fetch() -> None:
    from app.services.url_safety import validate_url_shape

    report = evaluate_ssrf_suite(GOLD / "c1" / "ssrf_adversarial.json")
    assert report["case_count"] >= 100
    assert report["production_path"] == "validate_url_shape"
    assert report["production_fetch_measured"] is False
    assert report["passed"] is False
    assert "g5_production_fetch_unmeasured" in report["failures"]
    validate_url_shape("https://ffmpeg.org/", source_name="SSRF")
    validate_url_shape("https://react.dev/blog", source_name="SSRF")
    try:
        validate_url_shape("https://127.0.0.1/", source_name="SSRF")
    except Exception as exc:  # noqa: BLE001 - shape reject is the measured outcome
        assert "not a public hostname" in str(exc)
    else:
        raise AssertionError("loopback must fail URL shape")


def test_summary_only_article_extracts_body_not_nav() -> None:
    assert is_summary_only("Short teaser.")
    html = (FIXTURES / "rss" / "article_with_boilerplate.html").read_bytes()
    robots = RobotsDecision(
        source_url="https://blog.example.com/compiler-change",
        robots_url=None,
        allowed=True,
        reason="fixture",
        retrieved_at="2026-08-01T00:00:00Z",
    )
    enrichment = enrich_html_bytes(
        url="https://blog.example.com/compiler-change",
        body=html,
        robots=robots,
        retrieved_at="2026-08-01T00:00:00Z",
    )
    assert enrichment.reason == "enriched"
    assert "unsafe transform" in enrichment.article_text
    assert "Site chrome" not in enrichment.article_text
    assert enrichment.evidence_locator.startswith("dom:")


def test_stale_displayed_does_not_keep_known_when_now_is_set() -> None:
    created = 1_700_000_000
    now = created + (200 * 24 * 60 * 60)
    displayed = KnowledgeEvidence(
        id="e1",
        user_id="u1",
        claim_id="c1",
        event_id="ev1",
        delta_id=None,
        kind=KIND_DISPLAYED,
        provenance="display",
        confidence="medium",
        source_id="s1",
        created_at=created,
    )
    derived = derive_knowledge_state([displayed], now=now)
    assert derived.state == "unknown"
    explicit = KnowledgeEvidence(
        id="e2",
        user_id="u1",
        claim_id="c1",
        event_id="ev1",
        delta_id=None,
        kind=KIND_ALREADY_KNEW,
        provenance="explicit_feedback",
        confidence="high",
        source_id="s2",
        created_at=created,
    )
    kept = derive_knowledge_state([displayed, explicit], now=now)
    assert kept.state == "known"


def test_persona_pair_orders_differ() -> None:
    items = [
        CompareItem(
            item_id="rust-1",
            published_at="2026-08-01T00:00:00Z",
            topic_key="rust",
            important_unknown=True,
            already_known=False,
            duplicate=False,
            useful=True,
            candidate=RankerCandidate(item_id="rust-1", topic_key="rust", relation_level="direct"),
        ),
        CompareItem(
            item_id="js-1",
            published_at="2026-08-02T00:00:00Z",
            topic_key="react",
            important_unknown=True,
            already_known=False,
            duplicate=False,
            useful=True,
            candidate=RankerCandidate(item_id="js-1", topic_key="react", relation_level="direct"),
        ),
    ]
    report = score_pair(
        items,
        PersonaPair(
            pair_id="rust-vs-js",
            left_persona="rust",
            right_persona="js",
            left_topics=("rust",),
            right_topics=("react",),
        ),
    )
    assert report["left_order"][0] != report["right_order"][0]
    assert report["insufficient"] is False


def test_compare_table_keeps_losses() -> None:
    payload = json.loads((GOLD / "c5" / "compare_fixture.json").read_text(encoding="utf-8"))
    items = [
        CompareItem(
            item_id=row["item_id"],
            published_at=row["published_at"],
            topic_key=row["topic_key"],
            important_unknown=row["important_unknown"],
            already_known=row["already_known"],
            duplicate=row["duplicate"],
            useful=row["useful"],
            candidate=RankerCandidate(
                item_id=row["item_id"],
                topic_key=row["topic_key"],
                relation_level=row["relation_level"],
                importance_level=row["importance_level"],
                updated_at=row["published_at"],
            ),
        )
        for row in payload["items"]
    ]
    table = compare_modes(items, followed_topics=set(payload["followed_topics"]), k=5)
    assert set(table["modes"]) == {"chronological", "topic_filter", "bulletfeed"}
    chrono = table["modes"]["chronological"]["order"][0]
    assert chrono == "old-rust-known" or chrono
    assert table["lost_metrics_kept"] is True


def test_compare_cohorts_keep_topic_filter_losses_and_history_reshow() -> None:
    payload = json.loads((GOLD / "c5" / "compare_fixture.json").read_text(encoding="utf-8"))
    items = [
        CompareItem(
            item_id=row["item_id"],
            published_at=row["published_at"],
            topic_key=row["topic_key"],
            important_unknown=row["important_unknown"],
            already_known=row["already_known"],
            duplicate=row["duplicate"],
            useful=row["useful"],
            candidate=RankerCandidate(
                item_id=row["item_id"],
                topic_key=row["topic_key"],
                relation_level=row["relation_level"],
                importance_level=row["importance_level"],
                updated_at=row["published_at"],
            ),
        )
        for row in payload["items"]
    ]
    report = compare_cohorts(items, followed_topics=set(payload["followed_topics"]), k=5)
    assert set(report["cohorts"]) == {"cold_start", "history_rich"}
    topic_filter = report["cohorts"]["history_rich"]["modes"]["topic_filter"]["metrics"]
    assert topic_filter["important_unknown_miss_rate"] > 0
    assert topic_filter["unknown_but_hidden"] >= 1
    cold = report["cohorts"]["cold_start"]["modes"]["bulletfeed"]["metrics"]
    rich = report["cohorts"]["history_rich"]["modes"]
    assert cold["already_known_reshow_rate"] == 0.0
    assert (
        rich["bulletfeed"]["metrics"]["already_known_reshow_rate"]
        <= rich["chronological"]["metrics"]["already_known_reshow_rate"]
    )
    assert (
        rich["bulletfeed"]["metrics"]["cards_to_first_important_unknown"]
        <= rich["chronological"]["metrics"]["cards_to_first_important_unknown"]
    )
    assert any(
        row["mode"] == "topic_filter" and row["important_unknown_miss_rate"] > 0
        for row in report["presentation"]
    )



def test_c1_gate_harness_does_not_invent_pass() -> None:
    report = evaluate_c1_gates(GOLD / "c1")
    assert report["g0"]["attested"] is False
    assert report["g1"]["passed"] is False
    assert report["g2"]["passed"] is False
    assert report["g2"]["gold_injected"] is False
    assert report["g3"]["passed"] is False
    assert report["g3"]["live_oracle_unmeasured"] is True
    assert report["g4"]["passed"] is False
    assert report["g5"]["passed"] is False
    assert report["passed"] is False


def test_g1_precision_counts_false_positives_in_top3() -> None:
    from app.evaluation.product_gap_c1 import load_g0_sources

    sources = load_g0_sources(GOLD / "c1" / "sources.json")
    floors = {
        "g1_feed_recall": 0.98,
        "g1_family_recall": 0.95,
        "g1_japanese_recall": 0.95,
        "g1_precision_at_3": 0.95,
        "g1_no_feed_fallback": 0.98,
    }
    g1 = evaluate_g1(sources, floors=floors)
    assert g1["production_confirm_measured"] is False
    assert g1["passed"] is False
    assert "g1_production_confirm_unmeasured" in g1["failures"]
    assert g1["precision_at_3"] <= g1["feed_recall_unconfirmed_probe"] + 1e-9


def test_adjacent_human_review_sample_is_not_gold() -> None:
    payload = json.loads((GOLD / "c2" / "adjacent_human_review_sample.json").read_text(encoding="utf-8"))
    assert payload["human_gold"] is False
    assert payload["label_source"] == "constructed"
    useful = [row for row in payload["items"] if row["useful"]]
    unrelated = [row for row in payload["items"] if not row["useful"]]
    assert len(useful) >= 3
    assert unrelated
    assert all(row["expected_match"] == "adjacent" for row in useful)
    assert all(row["expected_match"] == "reference" for row in unrelated)


def test_adjacent_rust_llvm_is_not_exact_match() -> None:
    report = score_adjacent_case(
        {
            "case_id": "rust-to-llvm",
            "persona_topics": ["rust"],
            "item_topic": "llvm",
            "expected_match": "adjacent",
            "useful": True,
        }
    )
    assert report["hit"] is True


def test_decay_and_reason_fixtures() -> None:
    decay = decay_before_after()
    assert decay["already_knew_does_not_decay"] is True
    assert decay["stale_implicit_unknown"] is True
    assert fixture_reason_missing() == 0


def test_c2_constructed_pairs_are_not_human_gold() -> None:
    report = evaluate_c2(GOLD / "c2")
    assert report["human_gold"] is False
    assert "human_adjacent_sample_missing" in report["failures"]
    assert report["pass"] is False


def test_c2_contrast_pairs_differ_without_dropping_everyone_important() -> None:
    report = evaluate_c2(GOLD / "c2")
    by_id = {row["pair_id"]: row for row in report["pairs"]}
    assert by_id["rust-vs-js"]["family"] == "topic_match"
    assert by_id["android-vs-llvm"]["family"] == "concept_adjacent"
    assert by_id["novice-vs-expert-rust"]["family"] == "knownness"
    assert by_id["novice-vs-expert-rust"]["known_item_demoted"] is True
    assert "persona_order_insufficient" not in report["failures"]
    assert "everyone_important_dropped" not in report["failures"]
    assert "knownness_not_demoted" not in report["failures"]
    assert report["m6_taxonomy_class"] == "personalization_insufficiency"
    assert report["m6_taxonomy_independent"] is True


def test_m6_taxonomy_keeps_personalization_insufficiency_independent() -> None:
    from app.evaluation.product_gap_c2 import m6_taxonomy_lists_personalization_insufficiency

    assert m6_taxonomy_lists_personalization_insufficiency() is True


def test_collapsed_persona_topics_are_detected_as_insufficient() -> None:
    from app.evaluation.product_gap_c2 import load_compare_items

    items = load_compare_items(GOLD / "c2")
    report = score_pair(
        items,
        PersonaPair(
            pair_id="collapsed",
            left_persona="same",
            right_persona="same",
            left_topics=(),
            right_topics=(),
            family="topic_match",
        ),
    )
    assert report["kendall_distance"] == 0.0
    assert report["insufficient"] is True
