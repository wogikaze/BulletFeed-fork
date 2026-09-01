"""Hard Completion Gate for #328 challenge 1.

Reads frozen floors and measurement artifacts only. Missing artifacts are
unmeasured, not an implicit 1.0. This module does not call production code
to invent a pass, and it does not keep unmeasured constants in source.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.evaluation.product_gap_c1 import evaluate_g0
from app.evaluation.product_gap_c1_artifacts import (
    MEASUREMENT_NAMES,
    compare_metrics,
    load_freeze,
    load_measurement,
)

GOLD_C1 = Path(__file__).resolve().parents[2] / "tests" / "gold" / "product_gap" / "c1" / "v2"

_G1_REQUIRED = {
    "g1_feed_recall": "feed_recall",
    "g1_precision_at_3": "precision_at_3",
    "g1_japanese_recall": "japanese_feed_recall",
    "g1_no_feed_fallback": "no_feed_fallback_rate",
}
_G2_REQUIRED = {
    "g2_primary_recall_at_20": "primary_recall_at_20",
    "g2_relevant_recall_at_50": "relevant_recall_at_50",
    "g2_precision_at_20": "precision_at_20",
}
_G3_REQUIRED = {
    "g3_raw_entry_recall": "raw_entry_recall",
    "g3_important_update_recall": "important_update_recall",
    "g3_duplicate_item_rate": "duplicate_item_rate",
}
_G4_REQUIRED = {
    "g4_body_success": "body_success",
    "g4_important_body_recall": "important_body_recall",
    "g4_update_recall": "update_recall",
    "g4_update_precision": "update_precision",
    "g4_boilerplate_fp": "boilerplate_fp",
    "g4_article_split": "article_split",
}
_REQUIRED = {
    "g1": _G1_REQUIRED,
    "g2": _G2_REQUIRED,
    "g3": _G3_REQUIRED,
    "g4": _G4_REQUIRED,
}


def evaluate_c1_hard_gate(gold_dir=None) -> dict[str, Any]:
    directory = gold_dir or GOLD_C1
    freeze = load_freeze(directory)
    g0 = evaluate_g0(directory)
    floors = {str(key): float(value) for key, value in freeze.get("metrics", {}).items()}
    g0_ok = bool(g0.floors_pass and g0.attested and freeze.get("final_blind_eligible"))
    g0_blockers = []
    if not freeze.get("final_blind_eligible"):
        g0_blockers.append("dataset_not_final_blind_eligible")
    if not g0.attested:
        g0_blockers.append("operator_attestation_pending")
    if not g0.floors_pass:
        g0_blockers.extend(g0.failures)

    gates: dict[str, dict[str, Any]] = {
        "g0": {
            "completion_gate_pass": g0_ok,
            "evidence": "frozen_corpus_and_operator_attestation",
            "dataset_version": freeze.get("dataset_version"),
            "blockers": g0_blockers,
        }
    }
    for name in MEASUREMENT_NAMES:
        artifact = load_measurement(directory, name)
        if artifact is None:
            gates[name] = {
                "status": "measurement_absent",
                "completion_gate_pass": artifact is not None,
                "evidence": "artifact_missing",
                "blockers": [f"{name}_measurement_absent"],
            }
            continue
        if name == "g5":
            version_ok = artifact.get("dataset_version") == freeze.get("dataset_version")
            sample_ok = artifact.get("sample_complete") is True
            fetch_ok = bool(artifact.get("production_fetch_measured"))
            identity_ok = bool(artifact.get("identity_measured"))
            live_ok = artifact.get("live_network_measured") is True
            shape_bypass_count = artifact.get("shape_bypass_count")
            shape_ok = shape_bypass_count is not None and int(shape_bypass_count) == 0
            gates[name] = {
                "status": "measured",
                "completion_gate_pass": (
                    version_ok and sample_ok and fetch_ok and identity_ok and shape_ok and live_ok
                ),
                "evidence": artifact.get("path") or "g5_measurement",
                "blockers": (
                    ([] if version_ok else ["g5_dataset_version_mismatch"])
                    + ([] if sample_ok else ["g5_sample_incomplete"])
                    + ([] if fetch_ok else ["g5_production_fetch_unmeasured"])
                    + ([] if identity_ok else ["g5_identity_unmeasured"])
                    + ([] if live_ok else ["g5_live_network_unmeasured"])
                    + ([] if shape_ok else ["g5_ssrf_shape_bypass"])
                ),
            }
            continue
        metrics = artifact.get("metrics") or {}
        failures = compare_metrics(metrics, floors, _REQUIRED.get(name, {}))
        if artifact.get("dataset_version") != freeze.get("dataset_version"):
            failures.append(f"{name}_dataset_version_mismatch")
        if artifact.get("sample_complete") is not True:
            failures.append(f"{name}_sample_incomplete")
        if name == "g1" and artifact.get("path") != "production_confirm":
            failures.append("g1_not_production_confirm")
        if name == "g2" and artifact.get("gold_injected"):
            failures.append("g2_gold_injected")
        if name == "g3" and artifact.get("live_oracle") is not True:
            failures.append("g3_live_oracle_unmeasured")
        if name == "g3" and artifact.get("family_regression_measured") is not True:
            failures.append("g3_family_regression_unmeasured")
        if name == "g3":
            failed_sources = artifact.get("failed_sources")
            if failed_sources is None or int(failed_sources) > 0:
                failures.append("g3_source_acquisition_failed")
        gates[name] = {
            "status": "measured",
            "completion_gate_pass": len(failures) == 0,
            "evidence": artifact.get("path") or f"{name}_measurement",
            "metric_failures": failures,
            "blockers": failures,
        }

    completion = all(item["completion_gate_pass"] for item in gates.values())
    blockers = [
        f"{name}:{blocker}"
        for name, item in gates.items()
        for blocker in item.get("blockers", [])
    ]
    return {
        "report_version": "product-gap-c1-hard-gate-audit-v2",
        "dataset_version": freeze.get("dataset_version"),
        "completion_gate_pass": completion,
        "gates": gates,
        "blockers": blockers,
    }
