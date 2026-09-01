"""Challenge-4 display-reason coverage and relation human-label intake."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.services.display_reason import DisplayReasonInputs, build_display_reason
from app.services.multiobjective_ranker import RANKING_POLICY_VERSION


def fixture_reason_missing() -> int:
    axes = (
        ("direct", "new_fact", "unknown"),
        ("adjacent", "detail", "probably_known"),
        ("reference", "correction", "known"),
        ("direct", "unresolved_conflict", "unknown"),
    )
    missing = 0
    for relation, delta, knownness in axes:
        reason = build_display_reason(
            DisplayReasonInputs(
                ranking_policy_version=RANKING_POLICY_VERSION,
                priority_rule="importance",
                redundancy_penalty=0.0,
                relation_level=relation,
                relation_reason=f"Matches {relation}",
                matched_topics=("rust",),
                matched_repository_names=(),
                importance_level="high",
                delta_type=delta,
                knownness_state=knownness,
                knownness_confidence="medium",
                additional_source_roles=(),
            )
        )
        if reason is None or not reason.text:
            missing += 1
    return missing


def evaluate_c4(gold_dir: Path, *, persona_reason_missing: int | None) -> dict[str, Any]:
    schema = json.loads((gold_dir / "label_schema.json").read_text(encoding="utf-8"))
    fixture_missing = fixture_reason_missing()
    labeled = schema.get("status") == "labeled" and len(schema.get("samples") or []) >= schema.get(
        "min_labeled_items", 40
    )
    failures = []
    if fixture_missing:
        failures.append("fixture_reason_missing")
    if persona_reason_missing not in {0, None} and persona_reason_missing > 0:
        failures.append("display_reason_missing")
    if not labeled:
        failures.append("human_relation_labels_missing")
    return {
        "fixture_reason_missing": fixture_missing,
        "persona_reason_missing": persona_reason_missing,
        "human_gold": bool(schema.get("human_gold")),
        "label_status": schema.get("status"),
        "pass": not failures,
        "failures": failures,
    }
