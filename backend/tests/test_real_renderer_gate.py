from __future__ import annotations

from pathlib import Path

from app.config import Settings
from app.evaluation.real_renderer_gate import (
    FORBIDDEN_ARCHITECTURES,
    MIN_E2E_RECALL_LOSS,
    MIN_PERSISTENT_PRIMARY_SOURCES,
    POLICY_VERSION,
    REQUIRED_ARCHITECTURE,
    E2EJsAttribution,
    StaticExtractionGap,
    evaluate_real_renderer_gate,
    js_only_important_unknown_recall_loss,
)
from app.evaluation.source_coverage import evaluate_source_coverage, load_source_coverage_gold


def _gap(
    source_id: str,
    *,
    origin: str = "live_authoritative",
    authority: str = "primary",
    persistent: bool = True,
    discovered: bool = True,
    static_fetch_ok: bool = True,
    static_normalize_insufficient: bool = True,
    js_render_would_recover: bool = True,
) -> StaticExtractionGap:
    return StaticExtractionGap(
        source_id=source_id,
        canonical_url=f"https://docs.example.com/{source_id}",
        authority=authority,
        persistent=persistent,
        discovered=discovered,
        static_fetch_ok=static_fetch_ok,
        static_normalize_insufficient=static_normalize_insufficient,
        js_render_would_recover=js_render_would_recover,
        origin=origin,
        observed_at="2026-08-29T00:00:00Z",
    )


def _e2e(
    case_id: str,
    *,
    hit: bool,
    recover: bool,
    origin: str = "live_authoritative",
    important: bool = True,
) -> E2EJsAttribution:
    return E2EJsAttribution(
        case_id=case_id,
        gold_important_unknown=important,
        surfaced_without_js=hit,
        would_surface_with_js=recover,
        origin=origin,
    )


def test_default_flag_stays_off_and_issue_stays_open() -> None:
    assert Settings().dynamic_web_enabled is False
    decision = evaluate_real_renderer_gate(())
    assert decision.policy_version == POLICY_VERSION
    assert decision.start_real_renderer is False
    assert decision.close_issue_64 is False
    assert decision.issue_64_remains_open is True
    assert decision.required_architecture == REQUIRED_ARCHITECTURE
    assert "in_process_playwright" in FORBIDDEN_ARCHITECTURES


def test_source_coverage_gap_is_ignored() -> None:
    corpus = load_source_coverage_gold(Path(__file__).parent / "gold" / "source_coverage" / "v01")
    report = evaluate_source_coverage(corpus, split="pilot")
    dynamic = next(row for row in report.by_source_family if row.key == "dynamic_web")
    assert dynamic.static_coverage_gap_rate == 1.0
    decision = evaluate_real_renderer_gate(
        (),
        source_coverage_static_gap_rate=dynamic.static_coverage_gap_rate,
    )
    assert decision.source_coverage_gap_ignored is True
    assert decision.start_real_renderer is False


def test_synthetic_gold_rows_do_not_count() -> None:
    gaps = [_gap(f"gold-{index}", origin="synthetic_gold") for index in range(8)]
    rows = [_e2e(f"e2e-{index}", hit=False, recover=True, origin="synthetic_gold") for index in range(8)]
    decision = evaluate_real_renderer_gate(gaps, rows, source_coverage_static_gap_rate=1.0)
    assert decision.persistent_primary_need_count == 0
    assert decision.e2e_js_only_recall_loss == 0.0
    assert decision.start_real_renderer is False


def test_four_live_primaries_do_not_start() -> None:
    gaps = [_gap(f"src-{index}") for index in range(4)]
    decision = evaluate_real_renderer_gate(gaps)
    assert decision.persistent_primary_need_count == 4
    assert decision.persistent_primary_need_count < MIN_PERSISTENT_PRIMARY_SOURCES
    assert decision.start_real_renderer is False


def test_five_live_primaries_start_isolated_service() -> None:
    gaps = [_gap(f"src-{index}") for index in range(5)]
    decision = evaluate_real_renderer_gate(gaps)
    assert decision.start_real_renderer is True
    assert "persistent_primary_sources=5" in decision.reasons[0]
    assert decision.required_architecture == "isolated_renderer_service"
    assert decision.close_issue_64 is False


def test_incomplete_pipeline_does_not_count() -> None:
    gaps = [
        _gap("a", discovered=False),
        _gap("b", static_fetch_ok=False),
        _gap("c", static_normalize_insufficient=False),
        _gap("d", js_render_would_recover=False),
        _gap("e", authority="secondary"),
        _gap("f", persistent=False),
    ]
    assert evaluate_real_renderer_gate(gaps).start_real_renderer is False


def test_e2e_loss_floor() -> None:
    below = [
        _e2e("a", hit=True, recover=False),
        _e2e("b", hit=True, recover=False),
        _e2e("c", hit=True, recover=False),
        _e2e("d", hit=True, recover=False),
        _e2e("e", hit=False, recover=False),
        _e2e("f", hit=True, recover=True),
    ]
    # 5/6 without JS. f already hits, so its recover flag does not add loss.
    assert js_only_important_unknown_recall_loss(below) < MIN_E2E_RECALL_LOSS
    assert evaluate_real_renderer_gate((), below).start_real_renderer is False

    at_floor = [
        _e2e("a", hit=True, recover=False),
        _e2e("b", hit=True, recover=False),
        _e2e("c", hit=True, recover=False),
        _e2e("d", hit=True, recover=False),
        _e2e("e", hit=False, recover=True),
        _e2e("f", hit=True, recover=False),
        _e2e("g", hit=True, recover=False),
        _e2e("h", hit=True, recover=False),
        _e2e("i", hit=True, recover=False),
        _e2e("j", hit=True, recover=False),
        _e2e("k", hit=True, recover=False),
        _e2e("l", hit=True, recover=False),
        _e2e("m", hit=True, recover=False),
        _e2e("n", hit=True, recover=False),
        _e2e("o", hit=True, recover=False),
        _e2e("p", hit=True, recover=False),
        _e2e("q", hit=True, recover=False),
        _e2e("r", hit=True, recover=False),
        _e2e("s", hit=True, recover=False),
        _e2e("t", hit=True, recover=False),
    ]
    # 19/20 actual, 20/20 recovered → 0.05
    assert abs(js_only_important_unknown_recall_loss(at_floor) - 0.05) < 1e-9
    decision = evaluate_real_renderer_gate((), at_floor)
    assert decision.start_real_renderer is True
    assert decision.e2e_js_only_recall_loss >= MIN_E2E_RECALL_LOSS


def test_representative_qualification_without_js_need_defers_issue_64() -> None:
    decision = evaluate_real_renderer_gate(
        (),
        live_endpoint_count=619,
        replay_case_count=3825,
    )
    assert decision.start_real_renderer is False
    assert decision.close_issue_64 is True
    assert decision.issue_64_remains_open is False
    assert any("defer_and_reopen" in reason for reason in decision.reasons)


def test_small_sample_does_not_close_issue_64() -> None:
    decision = evaluate_real_renderer_gate((), live_endpoint_count=50, replay_case_count=100)
    assert decision.close_issue_64 is False
    assert decision.issue_64_remains_open is True


def test_in_process_playwright_is_rejected_even_when_floors_pass() -> None:
    gaps = [_gap(f"src-{index}") for index in range(5)]
    decision = evaluate_real_renderer_gate(
        gaps,
        proposed_architecture="in_process_playwright",
    )
    assert decision.start_real_renderer is False
    assert any("forbidden" in reason for reason in decision.reasons)
