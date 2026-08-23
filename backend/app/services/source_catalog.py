from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SourceKind(StrEnum):
    GITHUB_RELEASE = "github_release"
    GITHUB_SBOM = "github_sbom"
    OSV = "osv"
    GITHUB_ADVISORY = "github_advisory"
    RSS_ATOM = "rss_atom"
    JSON_FEED = "json_feed"
    STATUSPAGE = "statuspage"
    HACKER_NEWS_DISCOVERY = "hacker_news_discovery"


class DiscoveryMethod(StrEnum):
    API = "api"
    WEBHOOK = "webhook"
    FEED = "feed"
    SITEMAP = "sitemap"
    STRUCTURED_HTML = "structured_html"
    HTML = "html"
    EXTERNAL_INDEX = "external_index"


@dataclass(frozen=True)
class SourcePolicy:
    kind: SourceKind
    priority: int
    discovery_method: DiscoveryMethod
    authoritative: bool
    discovery_only: bool = False


MVP_SOURCE_POLICIES: dict[SourceKind, SourcePolicy] = {
    SourceKind.GITHUB_RELEASE: SourcePolicy(SourceKind.GITHUB_RELEASE, 0, DiscoveryMethod.API, True),
    SourceKind.GITHUB_SBOM: SourcePolicy(SourceKind.GITHUB_SBOM, 0, DiscoveryMethod.API, True),
    SourceKind.OSV: SourcePolicy(SourceKind.OSV, 0, DiscoveryMethod.API, False),
    SourceKind.GITHUB_ADVISORY: SourcePolicy(SourceKind.GITHUB_ADVISORY, 1, DiscoveryMethod.API, True),
    SourceKind.RSS_ATOM: SourcePolicy(SourceKind.RSS_ATOM, 1, DiscoveryMethod.FEED, True),
    SourceKind.JSON_FEED: SourcePolicy(SourceKind.JSON_FEED, 1, DiscoveryMethod.FEED, True),
    SourceKind.STATUSPAGE: SourcePolicy(SourceKind.STATUSPAGE, 1, DiscoveryMethod.API, True),
    SourceKind.HACKER_NEWS_DISCOVERY: SourcePolicy(
        SourceKind.HACKER_NEWS_DISCOVERY,
        2,
        DiscoveryMethod.EXTERNAL_INDEX,
        False,
        discovery_only=True,
    ),
}


def get_source_policy(kind: SourceKind) -> SourcePolicy:
    return MVP_SOURCE_POLICIES[kind]


def source_allows_claim_evidence(source_type: str) -> bool:
    """Fail closed: only catalogued, non-discovery sources may support Claims."""
    try:
        policy = get_source_policy(SourceKind(source_type))
    except ValueError:
        return False
    return not policy.discovery_only
