from app.services.source_catalog import (
    DiscoveryMethod,
    SourceKind,
    get_source_policy,
    source_allows_claim_evidence,
)


def test_mvp_source_catalog_covers_all_primary_source_families() -> None:
    expected = {
        SourceKind.GITHUB_RELEASE,
        SourceKind.GITHUB_SBOM,
        SourceKind.OSV,
        SourceKind.GITHUB_ADVISORY,
        SourceKind.RSS_ATOM,
        SourceKind.STATUSPAGE,
        SourceKind.HACKER_NEWS_DISCOVERY,
    }

    for kind in expected:
        assert get_source_policy(kind).kind is kind


def test_hacker_news_is_discovery_only_not_evidence_authority() -> None:
    policy = get_source_policy(SourceKind.HACKER_NEWS_DISCOVERY)

    assert policy.discovery_only is True
    assert policy.authoritative is False
    assert policy.discovery_method is DiscoveryMethod.EXTERNAL_INDEX


def test_official_html_families_are_claim_evidence_eligible() -> None:
    for kind in (SourceKind.OFFICIAL_CHANGELOG, SourceKind.DOCUMENTATION):
        policy = get_source_policy(kind)
        assert policy.discovery_only is False
        assert policy.authoritative is True
        assert policy.discovery_method is DiscoveryMethod.STRUCTURED_HTML
        assert source_allows_claim_evidence(kind.value) is True


def test_generic_web_stays_discovery_only() -> None:
    policy = get_source_policy(SourceKind.GENERIC_WEB)
    assert policy.discovery_only is True
    assert source_allows_claim_evidence(SourceKind.GENERIC_WEB.value) is False


def test_structured_discovery_methods_exist_before_generic_html() -> None:
    assert DiscoveryMethod.API.value == "api"
    assert DiscoveryMethod.FEED.value == "feed"
    assert DiscoveryMethod.SITEMAP.value == "sitemap"
    assert DiscoveryMethod.STRUCTURED_HTML.value == "structured_html"
    assert DiscoveryMethod.HTML.value == "html"
