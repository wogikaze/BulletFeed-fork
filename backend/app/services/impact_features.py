"""Versioned impact feature contract for ranking and evaluators.

Rankers consume this snapshot, not raw Observation payloads.
"""

from __future__ import annotations

import json
from typing import Any, Final, Mapping

from app.services.impact_signals import extract_impact_signals, features_for_ranking

IMPACT_FEATURE_VERSION: Final = "impact-feature-v1"


def parse_observation_payload(payload_json: str | None) -> dict[str, Any]:
    if not payload_json:
        return {}
    try:
        loaded = json.loads(payload_json)
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def build_impact_record(
    *,
    source_type: str,
    source_key: str,
    delta_type: str,
    title: str,
    summary: str,
    payload: Mapping[str, Any] | None = None,
    claim_value: str = "",
    claim_detail: str = "",
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "impact_feature_version": IMPACT_FEATURE_VERSION,
        "source_type": source_type,
        "source_key": source_key,
        "delta_type": delta_type,
        "title": title,
        "summary": summary,
        "value": claim_value,
        "detail": claim_detail,
    }
    if payload:
        record["payload"] = dict(payload)
    return record


def ranking_impact_snapshot(record: Mapping[str, Any]) -> dict[str, Any]:
    return features_for_ranking(extract_impact_signals(record))
