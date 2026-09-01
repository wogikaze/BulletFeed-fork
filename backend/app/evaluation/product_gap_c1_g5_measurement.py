"""Measure the production URL-shape portion of G5 into an artifact.

This deliberately does not claim redirect/DNS/peer-fetch coverage.  Those
checks require a separate controlled transport or live qualification run and
remain explicit fields in the artifact instead of implicit PASS values.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.evaluation.product_gap_ssrf import evaluate_ssrf_suite


def measure_g5_shape(gold_dir: Path) -> dict[str, Any]:
    freeze = json.loads((gold_dir / "g0_freeze.json").read_text(encoding="utf-8"))
    suite = evaluate_ssrf_suite(gold_dir.parent / "ssrf_adversarial.json")
    return {
        "artifact_version": "product-gap-c1-g5-measurement-v1",
        "dataset_version": freeze.get("dataset_version"),
        "path": "production_validate_url_shape",
        "sample_complete": True,
        "case_count": suite.get("case_count"),
        "shape_bypass_count": suite.get("shape_bypass_count"),
        "shape_rejected": suite.get("rejected"),
        "production_fetch_measured": False,
        "identity_measured": False,
        "redirect_same_source_measured": False,
        "robots_not_success_measured": False,
        "bypasses": suite.get("bypasses"),
        "unmeasured": [
            "redirect_canonical_identity",
            "dns_rebinding_and_resolution_to_peer",
            "robots_policy_not_success",
            "production_fetch_transport",
        ],
    }
