"""Compare two source observations without synthesizing missing fetches."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

PROTOCOL_VERSION = "m3-longitudinal-protocol-v1"
Outcome = Literal[
    "unchanged",
    "updated",
    "conditional_304",
    "identity_change",
    "timeout",
    "http_error",
    "unavailable",
]


@dataclass(frozen=True)
class Observation:
    source_id: str
    source_family: str
    fetch_url: str
    acquired_at: str
    status_code: int | None
    final_url: str | None
    content_type: str | None
    content_hash: str | None
    etag: str | None
    last_modified: str | None
    error_type: str | None = None


def classify_pair(first: Observation, second: Observation | None) -> Outcome:
    """Classify a second observation against a prior one.

    A missing or failed second fetch is never treated as an update event.
    """
    if second is None:
        return "unavailable"
    if second.error_type == "timeout":
        return "timeout"
    if second.status_code is None:
        return "unavailable"
    if second.status_code == 304:
        return "conditional_304"
    if second.status_code == 429 or second.status_code >= 400:
        return "http_error"
    if first.final_url and second.final_url and first.final_url != second.final_url:
        return "identity_change"
    if second.content_hash and first.content_hash and second.content_hash == first.content_hash:
        return "unchanged"
    if second.content_hash and first.content_hash and second.content_hash != first.content_hash:
        return "updated"
    return "unavailable"


def summarize_outcomes(
    rows: Sequence[tuple[Observation, Observation | None]],
) -> dict[str, Any]:
    outcomes = [classify_pair(first, second) for first, second in rows]
    counts = Counter(outcomes)
    by_family: dict[str, Counter[str]] = {}
    for (first, _second), outcome in zip(rows, outcomes, strict=True):
        by_family.setdefault(first.source_family, Counter())[outcome] += 1
    observed_failures = [
        outcome
        for outcome in outcomes
        if outcome in {"timeout", "http_error", "identity_change"}
    ]
    unavailable = sum(1 for outcome in outcomes if outcome == "unavailable")
    if observed_failures:
        remediation = "required"
    elif unavailable:
        remediation = "collection_incomplete"
    else:
        remediation = "remediation_not_required"
    return {
        "protocol_version": PROTOCOL_VERSION,
        "pair_count": len(rows),
        "complete_pair_count": len(rows) - unavailable,
        "outcome_counts": dict(sorted(counts.items())),
        "by_source_family": {
            family: dict(sorted(counter.items()))
            for family, counter in sorted(by_family.items())
        },
        "observed_failure_count": len(observed_failures),
        "unavailable_count": unavailable,
        "remediation": remediation,
        "missing_second_fetch_not_counted_as_update": True,
    }


def observation_from_mapping(data: Mapping[str, Any]) -> Observation:
    status = data.get("status_code")
    return Observation(
        source_id=str(data["source_id"]),
        source_family=str(data["source_family"]),
        fetch_url=str(data["fetch_url"]),
        acquired_at=str(data["acquired_at"]),
        status_code=int(status) if isinstance(status, int) else None,
        final_url=data.get("final_url"),
        content_type=data.get("content_type"),
        content_hash=data.get("content_hash") or data.get("live_content_hash"),
        etag=data.get("etag"),
        last_modified=data.get("last_modified"),
        error_type=data.get("error_type"),
    )
