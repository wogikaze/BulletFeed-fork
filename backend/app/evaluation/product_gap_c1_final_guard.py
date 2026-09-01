"""Preflight guard for the one-shot G0 v2 blind evaluation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app.evaluation.product_gap_c1 import load_attestation
from app.evaluation.product_gap_c1_artifacts import load_freeze

DEFAULT_LOCK = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "gold"
    / "product_gap"
    / "c1"
    / "v2"
    / "final_evaluation_lock.json"
)


def audit_final_blind_preflight(
    gold_dir: Path,
    *,
    lock_path: Path | None = None,
) -> dict[str, Any]:
    lock_file = lock_path or (gold_dir / "final_evaluation_lock.json")
    freeze = load_freeze(gold_dir)
    attestation = load_attestation(gold_dir / "attestation.json")
    lock = (
        json.loads(lock_file.read_text(encoding="utf-8"))
        if lock_file.is_file()
        else {}
    )
    failures: list[str] = []
    source_hash = hashlib.sha256((gold_dir / "sources.json").read_bytes()).hexdigest()
    if freeze.get("final_blind_eligible") is not True:
        failures.append("dataset_not_final_blind_eligible")
    if freeze.get("sources_sha256") != source_hash:
        failures.append("sources_hash_mismatch")
    if attestation.get("dataset_version") != freeze.get("dataset_version"):
        failures.append("attestation_dataset_version_mismatch")
    if attestation.get("status") != "attested" or not attestation.get("attested_by"):
        failures.append("operator_attestation_pending")
    if lock.get("dataset_version") != freeze.get("dataset_version"):
        failures.append("lock_dataset_version_mismatch")
    if not isinstance(lock.get("production_sha"), str) or not lock["production_sha"].strip():
        failures.append("production_sha_unlocked")
    if lock.get("blind_status") != "not_started":
        failures.append("blind_already_started_or_invalid_status")
    result_path = lock.get("blind_result_path")
    if isinstance(result_path, str) and result_path.strip() and Path(result_path).exists():
        failures.append("blind_result_already_exists")
    return {
        "guard_version": "product-gap-c1-final-guard-v1",
        "dataset_version": freeze.get("dataset_version"),
        "lock_path": str(lock_file),
        "ready": not failures,
        "failures": failures,
    }
