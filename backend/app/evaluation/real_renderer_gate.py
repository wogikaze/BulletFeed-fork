"""When to start a real isolated JS renderer (Source-08 / #64).

Decision A+: the #114 contract may merge with the feature flag off.
Issue #64 stays open until a real browser renderer exists.

Source-09 ``dynamic_web`` gap is an intentional static-only visualization.
It must not start Playwright. Synthetic Gold JS cases do not count.

Start a real renderer only from live authoritative observations when either:

1. five or more persistent primary sources need JS after a successful static fetch
2. #72 important-unknown recall loses 5 percentage points to JS-only sources

The implementation must be an isolated renderer service, not Playwright inside
the FastAPI / sync-worker process.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

POLICY_VERSION = "real-renderer-gate-v1"
MIN_PERSISTENT_PRIMARY_SOURCES = 5
MIN_E2E_RECALL_LOSS = 0.05
REQUIRED_ARCHITECTURE = "isolated_renderer_service"
FORBIDDEN_ARCHITECTURES = frozenset(
    {
        "in_process_playwright",
        "backend_playwright_dependency",
        "playwright_in_fastapi",
    }
)
OriginName = Literal["live_authoritative", "synthetic_gold"]
AuthorityName = Literal["primary", "secondary"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StaticExtractionGap(_Strict):
    """One observed static-extraction failure on an authoritative Web source."""

    source_id: str = Field(min_length=1)
    canonical_url: str = Field(min_length=1)
    authority: AuthorityName
    persistent: bool
    discovered: bool
    static_fetch_ok: bool
    static_normalize_insufficient: bool
    js_render_would_recover: bool
    origin: OriginName
    observed_at: str = Field(min_length=1)


class E2EJsAttribution(_Strict):
    """#72 attribution used only for the renderer-start gate."""

    case_id: str = Field(min_length=1)
    gold_important_unknown: bool
    surfaced_without_js: bool
    would_surface_with_js: bool
    origin: OriginName


@dataclass(frozen=True)
class RendererGateDecision:
    policy_version: str
    start_real_renderer: bool
    reasons: tuple[str, ...]
    persistent_primary_need_count: int
    e2e_js_only_recall_loss: float
    source_coverage_gap_ignored: bool
    required_architecture: str
    issue_64_remains_open: bool
    close_issue_64: bool


def counts_as_persistent_primary_need(gap: StaticExtractionGap) -> bool:
    return (
        gap.origin == "live_authoritative"
        and gap.authority == "primary"
        and gap.persistent
        and gap.discovered
        and gap.static_fetch_ok
        and gap.static_normalize_insufficient
        and gap.js_render_would_recover
    )


def js_only_important_unknown_recall_loss(rows: Sequence[E2EJsAttribution]) -> float:
    """Counterfactual recall gain if JS-only misses were recovered.

    Synthetic Gold rows are ignored so designed fixtures cannot start Chromium.
    """
    intended = [
        row
        for row in rows
        if row.origin == "live_authoritative" and row.gold_important_unknown
    ]
    if not intended:
        return 0.0
    actual = sum(1 for row in intended if row.surfaced_without_js) / len(intended)
    recovered = sum(
        1
        for row in intended
        if row.surfaced_without_js or row.would_surface_with_js
    ) / len(intended)
    return recovered - actual


def evaluate_real_renderer_gate(
    observations: Sequence[StaticExtractionGap],
    e2e_rows: Sequence[E2EJsAttribution] = (),
    *,
    source_coverage_static_gap_rate: float | None = None,
    proposed_architecture: str = REQUIRED_ARCHITECTURE,
) -> RendererGateDecision:
    """Return whether #64 should start a real isolated renderer.

    ``source_coverage_static_gap_rate`` is accepted so callers can pass Source-09
    output. It is recorded as ignored and never used as a start condition.
    """
    del source_coverage_static_gap_rate
    needs = tuple(gap for gap in observations if counts_as_persistent_primary_need(gap))
    need_count = len({gap.source_id for gap in needs})
    recall_loss = js_only_important_unknown_recall_loss(e2e_rows)
    reasons: list[str] = []
    if need_count >= MIN_PERSISTENT_PRIMARY_SOURCES:
        reasons.append(
            f"persistent_primary_sources={need_count} >= {MIN_PERSISTENT_PRIMARY_SOURCES}"
        )
    if recall_loss >= MIN_E2E_RECALL_LOSS:
        reasons.append(
            f"e2e_js_only_recall_loss={recall_loss:.3f} >= {MIN_E2E_RECALL_LOSS:.2f}"
        )
    start = bool(reasons)
    if start and proposed_architecture in FORBIDDEN_ARCHITECTURES:
        reasons.append(
            f"architecture {proposed_architecture} is forbidden; use {REQUIRED_ARCHITECTURE}"
        )
        start = False
    if start and proposed_architecture != REQUIRED_ARCHITECTURE:
        reasons.append(
            f"architecture {proposed_architecture} is not {REQUIRED_ARCHITECTURE}"
        )
        start = False
    if not reasons:
        reasons.append("live evidence is below the real-renderer start floors")
    return RendererGateDecision(
        policy_version=POLICY_VERSION,
        start_real_renderer=start,
        reasons=tuple(reasons),
        persistent_primary_need_count=need_count,
        e2e_js_only_recall_loss=recall_loss,
        source_coverage_gap_ignored=True,
        required_architecture=REQUIRED_ARCHITECTURE,
        issue_64_remains_open=True,
        close_issue_64=False,
    )
