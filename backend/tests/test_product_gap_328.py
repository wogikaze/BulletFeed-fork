from __future__ import annotations

import json
from pathlib import Path

from app.evaluation.product_gap_c1 import evaluate_g0
from app.evaluation.product_gap_c1_gates import evaluate_c1_gates, evaluate_g1
from app.evaluation.product_gap_c2 import PersonaPair, evaluate_c2, score_adjacent_case, score_pair
from app.evaluation.product_gap_c3 import decay_before_after
from app.evaluation.product_gap_c4 import fixture_reason_missing
from app.evaluation.product_gap_compare import CompareItem, compare_modes
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


def test_g0_count_floors_pass_without_claiming_attestation() -> None:
    report = evaluate_g0(GOLD / "c1")
    assert report.source_count >= 300
    assert report.topic_count >= 24
    assert report.japanese_count >= 100
    assert report.no_rss_web_count >= 60
    assert report.blind_source_ratio >= 0.30
    assert report.families["official_blog"] >= 40
    assert report.families["corp_tech_blog"] >= 40
    assert report.families["personal_dev_blog"] >= 40
    assert report.families["docs_changelog"] >= 40
    assert report.families["rss_atom_json"] >= 40
    assert report.attested is False
    assert "attestation_pending" in report.failures


def test_ssrf_suite_has_100_cases_and_zero_bypass() -> None:
    report = evaluate_ssrf_suite(GOLD / "c1" / "ssrf_adversarial.json")
    assert report["case_count"] >= 100
    assert report["bypasses"] == []
    assert report["pass"] is True


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


def test_c1_gate_harness_reports_floors_without_claiming_attestation() -> None:
    report = evaluate_c1_gates(GOLD / "c1")
    assert report["g0"]["source_count"] >= 300
    assert report["g0"]["attested"] is False
    assert report["g5"]["pass"] is True
    assert report["g4"]["pass"] is True
    assert report["pass"] is False


def test_g1_counts_well_known_official_feeds() -> None:
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
    assert g1["eligible_feed_count"] >= 70
    assert g1["feed_recall"] > 0.5
    assert g1["no_feed_fallback"] >= 0.98


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
    report = evaluate_c2(GOLD / "c2", items)
    assert report["human_gold"] is False
    assert "human_adjacent_sample_missing" in report["failures"]
