"""Challenge-3 decay measurement and unknown-but-hidden hard gate."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.evaluation.product_release_gate import HARD_METRICS
from app.services.knowledge_evidence import (
    KIND_ALREADY_KNEW,
    KIND_DISPLAYED,
    KnowledgeEvidence,
    derive_knowledge_state,
)
from app.services.knownness_decay import DECAY_POLICY_VERSION


def decay_before_after() -> dict[str, Any]:
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
    stale = derive_knowledge_state([displayed], now=now)
    frozen = derive_knowledge_state([displayed], now=None)
    kept = derive_knowledge_state([displayed, explicit], now=now)
    return {
        "policy_version": DECAY_POLICY_VERSION,
        "stale_displayed_state": stale.state,
        "fixture_clock_state": frozen.state,
        "already_knew_state": kept.state,
        "already_knew_does_not_decay": kept.state == "known",
        "stale_implicit_unknown": stale.state == "unknown",
    }


def evaluate_c3(gold_dir: Path, *, unknown_but_hidden: int) -> dict[str, Any]:
    protocol = json.loads((gold_dir / "human_protocol.json").read_text(encoding="utf-8"))
    decay = decay_before_after()
    people = int(protocol.get("people") or 0)
    failures = []
    if people < int(protocol.get("min_people") or 5):
        failures.append("human_knownness_n_lt_5")
    if unknown_but_hidden > 0:
        failures.append("unknown_but_hidden")
    if not decay["already_knew_does_not_decay"] or not decay["stale_implicit_unknown"]:
        failures.append("decay_policy")
    return {
        "hard_metrics": list(HARD_METRICS),
        "unknown_but_hidden": unknown_but_hidden,
        "decay": decay,
        "protocol": protocol,
        "pass": not failures,
        "failures": failures,
    }
