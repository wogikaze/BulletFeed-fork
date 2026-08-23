from __future__ import annotations

import re
from typing import Any

from app.stores.observation_store import Observation

_GHSA_PATTERN = re.compile(
    r"\bGHSA-[23456789cfghjmpqrvwxy]{4}-[23456789cfghjmpqrvwxy]{4}-"
    r"[23456789cfghjmpqrvwxy]{4}\b",
    re.IGNORECASE,
)


def evidence_dependence_key(observation: Observation) -> str:
    """Return an upstream evidence-family key, not a source-count key.

    OSV often republishes/adapts an advisory whose upstream identity is a GHSA. In
    that case OSV and GitHub Advisory evidence share one dependence key and must not
    be counted as independent corroboration merely because they arrived from two
    APIs. GitHub duplicate advisories also share the canonical advisory's key.
    Other observations remain independent unless a stronger lineage identity is known.
    """
    if observation.source_type == "github_advisory":
        ghsa = canonical_github_advisory_id(observation.payload)
        if ghsa:
            return f"advisory:{ghsa}"

    if observation.source_type == "osv":
        vulnerability = _osv_vulnerability(observation.payload)
        ghsa = _github_advisory_id(vulnerability)
        if ghsa:
            return f"advisory:{ghsa}"
        vulnerability_id = vulnerability.get("id")
        if isinstance(vulnerability_id, str) and vulnerability_id:
            return f"osv:{vulnerability_id}"

    if observation.source_type == "github_sbom":
        return f"sbom:{observation.source_key}:{observation.source_observation_id}"

    return f"observation:{observation.id}"


def canonical_github_advisory_id(payload: dict[str, Any]) -> str | None:
    """Resolve GitHub's explicitly withdrawn duplicate advisories to their target GHSA."""
    direct = _github_advisory_id(payload)
    if direct is None:
        return None

    summary = payload.get("summary")
    description = payload.get("description")
    duplicate_marker = (
        isinstance(summary, str) and summary.lower().startswith("duplicate advisory")
    ) or (
        isinstance(description, str) and "duplicate" in description.lower()
    )
    if not duplicate_marker:
        return direct

    candidates: set[str] = set()
    if isinstance(description, str):
        candidates.update(match.upper() for match in _GHSA_PATTERN.findall(description))
    references = payload.get("references")
    if isinstance(references, list):
        for reference in references:
            if isinstance(reference, dict):
                url = reference.get("url")
            else:
                url = reference
            if isinstance(url, str):
                candidates.update(match.upper() for match in _GHSA_PATTERN.findall(url))
    candidates.discard(direct.upper())
    return sorted(candidates)[0] if candidates else direct


def _osv_vulnerability(payload: dict[str, Any]) -> dict[str, Any]:
    nested = payload.get("vulnerability")
    return nested if isinstance(nested, dict) else payload


def _github_advisory_id(payload: dict[str, Any]) -> str | None:
    direct = payload.get("ghsa_id")
    if isinstance(direct, str) and direct.upper().startswith("GHSA-"):
        return direct.upper()

    identifier = payload.get("id")
    if isinstance(identifier, str) and identifier.upper().startswith("GHSA-"):
        return identifier.upper()

    aliases = payload.get("aliases")
    if isinstance(aliases, list):
        candidates = sorted(
            alias.upper()
            for alias in aliases
            if isinstance(alias, str) and alias.upper().startswith("GHSA-")
        )
        if candidates:
            return candidates[0]
    return None
