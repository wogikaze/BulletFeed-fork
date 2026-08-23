from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_CORRECTION_PATTERNS = (
    re.compile(r"\bcorrection\s*:", re.IGNORECASE),
    re.compile(r"\bprevious update (?:was|is) incorrect\b", re.IGNORECASE),
    re.compile(
        r"\bwe previously (?:stated|reported).{0,80}\b(?:incorrect|wrong)\b",
        re.IGNORECASE,
    ),
)


@dataclass(frozen=True)
class StatuspageIncidentObservation:
    page_id: str
    incident_id: str
    update_id: str
    incident_name: str
    status: str
    body: str
    impact: str
    published_at: str
    updated_at: str
    original_url: str
    raw: dict[str, Any]
    explicit_correction: bool = False

    @property
    def event_key(self) -> str:
        return f"statuspage:{self.page_id}:{self.incident_id}"


def normalize_incident_updates(
    page_id: str,
    summary: dict[str, Any],
) -> list[StatuspageIncidentObservation]:
    normalized: list[StatuspageIncidentObservation] = []
    incidents = summary.get("incidents")
    if not isinstance(incidents, list):
        return normalized

    for incident in incidents:
        if not isinstance(incident, dict):
            continue
        incident_id = _required_text(incident, "id")
        incident_name = _required_text(incident, "name")
        impact = _optional_text(incident, "impact", "none")
        original_url = _optional_text(
            incident,
            "shortlink",
            f"https://{page_id}.statuspage.io/incidents/{incident_id}",
        )
        incident_identity = {
            "id": incident_id,
            "name": incident_name,
            "created_at": _required_text(incident, "created_at"),
            "shortlink": original_url,
        }
        updates = incident.get("incident_updates")
        if not isinstance(updates, list):
            continue

        for update in updates:
            if not isinstance(update, dict):
                continue
            update_id = _required_text(update, "id")
            status = _required_text(update, "status")
            published_at = _optional_text(
                update,
                "display_at",
                _optional_text(update, "created_at", incident_identity["created_at"]),
            )
            updated_at = _optional_text(update, "updated_at", published_at)
            body = _optional_text(update, "body", "")
            normalized.append(
                StatuspageIncidentObservation(
                    page_id=page_id,
                    incident_id=incident_id,
                    update_id=update_id,
                    incident_name=incident_name,
                    status=status,
                    body=body,
                    impact=impact,
                    published_at=published_at,
                    updated_at=updated_at,
                    original_url=original_url,
                    raw={"incident": incident_identity, "update": update},
                    explicit_correction=_has_explicit_correction(body),
                )
            )

    normalized.sort(key=lambda item: (item.published_at, item.updated_at, item.update_id))
    return normalized


def _has_explicit_correction(body: str) -> bool:
    return any(pattern.search(body) is not None for pattern in _CORRECTION_PATTERNS)


def _required_text(value: dict[str, Any], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result:
        raise ValueError(f"Statuspage field {key!r} is required")
    return result


def _optional_text(value: dict[str, Any], key: str, default: str) -> str:
    result = value.get(key)
    return result if isinstance(result, str) and result else default
