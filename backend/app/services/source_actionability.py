"""Single routing table from source family to product activation.

Discovery-only and evidence eligibility stay separate from whether the user
can actually activate a candidate. Missing families fail closed as unsupported.
"""

from __future__ import annotations

from typing import Literal

from app.services.source_catalog import SourceKind
from app.services.source_discovery_seeds import DiscoveryProvenance

SourceActionability = Literal[
    "subscribe",
    "select_repository",
    "discovery_only",
    "unsupported",
]

# Every SourceKind must have an explicit product action. Do not infer from
# discovery_only policy: that flag is about Claim evidence, not watchability.
SOURCE_FAMILY_ACTIONS: dict[str, SourceActionability] = {
    SourceKind.RSS_ATOM.value: "subscribe",
    SourceKind.JSON_FEED.value: "subscribe",
    SourceKind.STATUSPAGE.value: "subscribe",
    SourceKind.GENERIC_WEB.value: "subscribe",
    SourceKind.GITHUB_RELEASE.value: "select_repository",
    SourceKind.HACKER_NEWS_DISCOVERY.value: "discovery_only",
    SourceKind.GITHUB_ADVISORY.value: "unsupported",
    SourceKind.OSV.value: "unsupported",
    SourceKind.GITHUB_SBOM.value: "unsupported",
    SourceKind.OFFICIAL_CHANGELOG.value: "unsupported",
    SourceKind.DOCUMENTATION.value: "unsupported",
}

_APPROVABLE = frozenset({"subscribe", "select_repository"})


def resolve_source_actionability(
    *,
    family: str,
    discovery_provenance: str | None = None,
    discovery_only: bool = False,
) -> SourceActionability:
    del discovery_only  # evidence flag; not a product activation signal
    if (
        discovery_provenance == DiscoveryProvenance.EXTERNAL_INDEX.value
        or family == SourceKind.HACKER_NEWS_DISCOVERY.value
    ):
        return "discovery_only"
    return SOURCE_FAMILY_ACTIONS.get(family, "unsupported")


def actionability_allows_approve(actionability: str) -> bool:
    return actionability in _APPROVABLE


def missing_source_family_actions() -> tuple[str, ...]:
    expected = {kind.value for kind in SourceKind}
    return tuple(sorted(expected - set(SOURCE_FAMILY_ACTIONS)))
