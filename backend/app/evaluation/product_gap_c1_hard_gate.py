"""Honest completion audit for #328 challenge 1.

The deterministic G1-G5 harness is useful regression evidence, but several
parts deliberately replay the frozen catalog or controlled fixtures.  This
module prevents those results from being confused with the Hard Completion
Gate written in #328.  Missing real-world/independent evidence is a FAIL, not
an implicit 1.0.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.evaluation.product_gap_c1_gates import GOLD_C1, evaluate_c1_gates

INCOMPLETE = bool(0)


def evaluate_c1_hard_gate(gold_dir: Path | None = None) -> dict[str, Any]:
    directory = gold_dir or GOLD_C1
    replay = evaluate_c1_gates(directory)

    g0 = replay["g0"]
    g1 = replay["g1"]
    g2 = replay["g2"]
    g3 = replay["g3"]
    g4 = replay["g4"]
    g5 = replay["g5"]

    gates: dict[str, dict[str, Any]] = {
        "g0": {
            "completion_gate_pass": bool(g0.get("floors_pass") and g0.get("attested")),
            "evidence": "frozen_corpus_and_operator_attestation",
            "blockers": [] if g0.get("attested") else ["operator_attestation_pending"],
        },
        "g1": {
            "deterministic_replay_pass": bool(g1.get("pass")),
            "completion_gate_pass": INCOMPLETE,
            "evidence": "well_known_path_catalog_replay",
            "blockers": [
                "live_site_url_discovery_recall_unmeasured",
                "live_candidate_precision_at_3_unmeasured",
                "live_no_feed_fallback_unmeasured",
            ],
        },
        "g2": {
            "deterministic_replay_pass": bool(g2.get("pass")),
            "completion_gate_pass": INCOMPLETE,
            "evidence": "g0_catalog_hints_replay_not_independent_discovery",
            "blockers": ["independent_topic_to_source_discovery_unmeasured"],
        },
        "g3": {
            "fixture_rss_parity_pass": bool(g3.get("pass")),
            "completion_gate_pass": INCOMPLETE,
            "evidence": "controlled_rss_fixture_only",
            "reported_bulletfeed_universe_recall_accepted": False,
            "reported_breadth_superiority_accepted": False,
            "blockers": [
                "live_rss_oracle_parity_unmeasured",
                "real_source_breadth_superiority_unmeasured",
            ],
        },
        "g4": {
            "fixture_body_extraction_pass": bool(g4.get("pass")),
            "completion_gate_pass": INCOMPLETE,
            "evidence": "single_controlled_article_fixture",
            "update_recall": None,
            "update_precision": None,
            "blockers": [
                "real_article_body_recall_unmeasured",
                "longitudinal_update_recall_unmeasured",
                "longitudinal_update_precision_unmeasured",
            ],
        },
        "g5": {
            "deterministic_ssrf_pass": bool((g5.get("ssrf") or {}).get("pass")),
            "completion_gate_pass": INCOMPLETE,
            "evidence": "ssrf_suite_plus_separate_integration_tests",
            "blockers": ["identity_policy_results_not_derived_by_gate_harness"],
        },
    }

    completion = all(item["completion_gate_pass"] for item in gates.values())
    blockers = [
        f"{name}:{blocker}"
        for name, item in gates.items()
        for blocker in item.get("blockers", [])
    ]
    return {
        "report_version": "product-gap-c1-hard-gate-audit-v1",
        "deterministic_report_version": replay.get("report_version"),
        "completion_gate_pass": completion,
        "gates": gates,
        "blockers": blockers,
    }
