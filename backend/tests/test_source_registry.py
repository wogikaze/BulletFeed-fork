from pathlib import Path

import pytest

from app.database import Database
from app.services.source_catalog import DiscoveryMethod, SourceKind, source_allows_claim_evidence
from app.services.source_ingestion import NormalizedObservation, SourceIngestionPipeline
from app.services.source_registry import (
    AuthorityStatus,
    Endpoint,
    SourceRegistry,
    VerificationStatus,
    canonicalize_url,
    endpoint_allows_claim_evidence,
    endpoint_id,
    find_duplicate_endpoint,
    publisher_id,
)


def test_publisher_and_endpoint_ids_are_stable_and_replayable() -> None:
    first_publisher = publisher_id(slug="GitHub")
    second_publisher = publisher_id(slug=" github ")
    first_endpoint = endpoint_id(url="https://github.com/blog/feed/", family=SourceKind.RSS_ATOM)
    second_endpoint = endpoint_id(
        url="http://www.github.com/blog/feed?utm_source=share#top",
        family="rss_atom",
    )

    assert first_publisher == second_publisher
    assert first_publisher.startswith("pub_")
    assert first_endpoint == second_endpoint
    assert first_endpoint.startswith("ep_")
    assert publisher_id(homepage_url="https://status.github.com/") != first_publisher


def test_canonicalize_url_handles_trivial_variants_without_merging_hosts() -> None:
    canonical = canonicalize_url("https://example.com/feed")
    assert canonicalize_url("http://www.example.com/feed/") == canonical
    assert canonicalize_url("https://example.com:443/feed") == canonical
    assert canonicalize_url("http://example.com:80/feed#section") == canonical
    assert canonicalize_url("https://example.com/feed?utm_source=tw&b=2&a=1") == canonicalize_url(
        "https://example.com/feed?a=1&b=2"
    )
    assert canonicalize_url("https://status.github.com/") != canonicalize_url("https://github.com/")
    assert canonicalize_url("https://github.com/blog") != canonicalize_url(
        "https://github.com/advisories"
    )


def test_publisher_aliases_share_identity_across_urls() -> None:
    registry = SourceRegistry(seed_mvp=False)
    github = registry.register_publisher(
        slug="github",
        display_name="GitHub",
        homepage_url="https://github.com",
        aliases=("www.github.com", "https://api.github.com"),
        created_at="2026-08-01T00:00:00Z",
    )
    again = registry.register_publisher(
        slug="GitHub",
        display_name="GitHub, Inc.",
        homepage_url="https://www.github.com/",
        aliases=("https://github.blog",),
        created_at="2026-08-02T00:00:00Z",
    )

    assert again.publisher_id == github.publisher_id
    assert registry.find_publisher(url="http://www.github.com/").publisher_id == github.publisher_id
    assert registry.find_publisher(url="https://api.github.com/").publisher_id == github.publisher_id
    assert registry.find_publisher(url="https://github.blog/").publisher_id == github.publisher_id
    assert registry.find_publisher(slug="github").publisher_id == github.publisher_id


def test_one_publisher_can_own_multiple_families_and_endpoints() -> None:
    registry = SourceRegistry()
    github = registry.find_publisher(slug="github")
    assert github is not None
    endpoints = registry.list_endpoints(publisher_id=github.publisher_id)
    families = {item.family for item in endpoints}

    assert SourceKind.GITHUB_RELEASE in families
    assert SourceKind.GITHUB_ADVISORY in families
    assert SourceKind.RSS_ATOM in families
    assert len(endpoints) >= 3
    assert len({item.endpoint_id for item in endpoints}) == len(endpoints)


def test_same_domain_unrelated_services_stay_distinct() -> None:
    registry = SourceRegistry(seed_mvp=True)
    github = registry.find_publisher(slug="github")
    assert github is not None

    blog = registry.register_endpoint(
        url="https://github.com/blog",
        family=SourceKind.RSS_ATOM,
        created_at="2026-08-01T00:00:00Z",
    )
    advisories = registry.register_endpoint(
        url="https://github.com/advisories",
        family=SourceKind.GITHUB_ADVISORY,
        created_at="2026-08-01T00:00:00Z",
    )
    status = registry.register_endpoint(
        url="https://status.github.com",
        family=SourceKind.STATUSPAGE,
        created_at="2026-08-01T00:00:00Z",
    )

    assert len({blog.endpoint_id, advisories.endpoint_id, status.endpoint_id}) == 3
    assert blog.publisher_id == github.publisher_id
    assert advisories.publisher_id == github.publisher_id
    assert status.publisher_id != github.publisher_id
    assert registry.get_publisher(status.publisher_id).slug == "status.github.com"
    assert endpoint_allows_claim_evidence(blog) is True
    assert endpoint_allows_claim_evidence(advisories) is True
    assert endpoint_allows_claim_evidence(status) is True

    shared = registry.register_endpoint(
        url="https://www.githubstatus.com/api/v2/summary.json",
        family=SourceKind.STATUSPAGE,
        publisher_slug="github",
        created_at="2026-08-01T00:00:00Z",
    )
    assert shared.publisher_id == github.publisher_id
    assert shared.endpoint_id != blog.endpoint_id
    assert shared.family == SourceKind.STATUSPAGE


def test_register_endpoint_returns_existing_id_before_scheduling() -> None:
    registry = SourceRegistry(seed_mvp=False)
    first = registry.register_endpoint(
        url="https://engineering.acme.example/feed.xml",
        family=SourceKind.RSS_ATOM,
        created_at="2026-08-01T00:00:00Z",
    )
    second = registry.register_endpoint(
        url="http://www.engineering.acme.example/feed.xml/?utm_campaign=share",
        family="rss_atom",
        created_at="2026-08-02T00:00:00Z",
    )
    found = find_duplicate_endpoint(
        registry,
        "https://engineering.acme.example/feed.xml/",
        family=SourceKind.RSS_ATOM,
    )

    assert second.endpoint_id == first.endpoint_id
    assert found is not None
    assert found.endpoint_id == first.endpoint_id
    assert registry.detect_duplicate(
        "https://engineering.acme.example/feed.xml",
        family=SourceKind.RSS_ATOM,
    ).endpoint_id == first.endpoint_id
    assert first.discovery_method == DiscoveryMethod.FEED
    assert first.verification_status == VerificationStatus.VERIFIED
    assert first.authority_status == AuthorityStatus.AUTHORITATIVE


def test_runtime_verification_metadata_round_trips_without_changing_identity(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "verification.db")
    database.initialize()
    registry = SourceRegistry(database, seed_mvp=False)
    endpoint = registry.register_endpoint(
        url="https://engineering.acme.example/feed.xml",
        family="web_scrape",
        created_at="2026-08-30T00:00:00Z",
    )

    verified = registry.record_verification(
        endpoint.endpoint_id,
        verification_status=VerificationStatus.VERIFIED,
        verification_method="https_get_and_dns",
        verification_reference="https://engineering.acme.example/feed.xml#verified",
        verified_at="2026-08-30T01:00:00Z",
        authority_status=AuthorityStatus.AUTHORITATIVE,
        authority_method="publisher_registry",
        authority_reference="https://engineering.acme.example/about",
        authority_verified_at="2026-08-30T01:00:00Z",
    )
    reloaded = SourceRegistry(database, seed_mvp=False).get_endpoint(endpoint.endpoint_id)

    assert reloaded is not None
    assert verified.endpoint_id == endpoint.endpoint_id
    assert verified.canonical_url == endpoint.canonical_url
    assert reloaded.verification_status == VerificationStatus.VERIFIED
    assert reloaded.verification_method == "https_get_and_dns"
    assert reloaded.verification_reference.endswith("#verified")
    assert reloaded.verified_at == "2026-08-30T01:00:00Z"
    assert reloaded.authority_status == AuthorityStatus.AUTHORITATIVE
    assert reloaded.authority_method == "publisher_registry"
    assert reloaded.authority_reference.endswith("/about")
    assert reloaded.authority_verified_at == "2026-08-30T01:00:00Z"


def test_runtime_verification_requires_evidence_for_positive_status(tmp_path: Path) -> None:
    database = Database(tmp_path / "verification-required.db")
    database.initialize()
    registry = SourceRegistry(database, seed_mvp=False)
    endpoint = registry.register_endpoint(
        url="https://engineering.acme.example/feed.xml",
        family="web_scrape",
    )

    with pytest.raises(ValueError, match="method, reference, and verified_at"):
        registry.record_verification(
            endpoint.endpoint_id,
            verification_status=VerificationStatus.VERIFIED,
            verification_method=None,
            verification_reference=None,
            verified_at=None,
            authority_status=AuthorityStatus.UNKNOWN,
        )


def test_redirect_preserves_lineage_without_rewriting_observations(tmp_path: Path) -> None:
    database = Database(tmp_path / "lineage.db")
    database.initialize()
    old_url = "https://engineering.acme.example/old/feed.xml"
    new_url = "https://engineering.acme.example/new/feed.xml"
    observations = SourceIngestionPipeline(database).ingest_many(
        (
            NormalizedObservation(
                source_type="rss_atom",
                source_key=old_url,
                source_observation_id="item-1",
                payload={"title": "Widget 2.0"},
                original_url=f"{old_url}#item-1",
                published_at="2026-08-20T10:00:00Z",
            ),
        ),
        retrieved_at="2026-08-20T10:01:00Z",
    )
    registry = SourceRegistry(database, seed_mvp=False)
    moved = registry.record_redirect(
        previous_url=old_url,
        current_url=new_url,
        family=SourceKind.RSS_ATOM,
        reason="moved",
        recorded_at="2026-08-21T00:00:00Z",
    )

    previous = registry.find_duplicate_endpoint(old_url, family=SourceKind.RSS_ATOM)
    assert previous is not None
    assert moved.endpoint_id != previous.endpoint_id
    assert moved.previous_endpoint_id == previous.endpoint_id
    assert moved.redirect_of == previous.endpoint_id
    assert observations[0].source_key == old_url
    lineage = registry.lineage_for(moved.endpoint_id)
    assert [(row.from_endpoint_id, row.to_endpoint_id, row.reason) for row in lineage] == [
        (previous.endpoint_id, moved.endpoint_id, "moved")
    ]
    with database.connect() as connection:
        stored_key = connection.execute(
            "SELECT source_key FROM observations WHERE id = ?",
            (observations[0].id,),
        ).fetchone()["source_key"]
    assert stored_key == old_url


def test_endpoint_allows_claim_evidence_delegates_and_stays_fail_closed() -> None:
    registry = SourceRegistry()
    github = registry.find_duplicate_endpoint(
        "https://api.github.com",
        family=SourceKind.GITHUB_RELEASE,
    )
    hn = registry.find_duplicate_endpoint(
        "https://hacker-news.firebaseio.com/v0/topstories.json",
        family=SourceKind.HACKER_NEWS_DISCOVERY,
    )
    unknown = registry.register_endpoint(
        url="https://pages.example/notes",
        family="web_scrape",
        created_at="2026-08-01T00:00:00Z",
    )

    assert github is not None
    assert hn is not None
    assert endpoint_allows_claim_evidence(github) is True
    assert endpoint_allows_claim_evidence(hn) is False
    assert endpoint_allows_claim_evidence(unknown) is False
    assert endpoint_allows_claim_evidence(github) == source_allows_claim_evidence(github.family)
    assert endpoint_allows_claim_evidence(hn) == source_allows_claim_evidence(hn.family)
    assert endpoint_allows_claim_evidence(
        Endpoint(
            endpoint_id="ep_dummy",
            publisher_id="pub_dummy",
            family="not-a-catalog-kind",
            canonical_url="https://example.com",
            registered_url="https://example.com",
            discovery_method="html",
            verification_status=VerificationStatus.UNVERIFIED,
            authority_status=AuthorityStatus.UNKNOWN,
            created_at="2026-08-01T00:00:00Z",
        )
    ) is False


def test_mvp_seeds_catalog_families_as_discoverable_entries() -> None:
    registry = SourceRegistry()
    families = {item.family for item in registry.list_endpoints()}
    assert SourceKind.GITHUB_RELEASE in families
    assert SourceKind.OSV in families
    assert SourceKind.GITHUB_ADVISORY in families
    assert SourceKind.STATUSPAGE in families
    assert SourceKind.RSS_ATOM in families
    assert SourceKind.JSON_FEED in families
    osv = registry.find_publisher(slug="osv")
    assert osv is not None
    assert len(registry.list_endpoints(publisher_id=osv.publisher_id)) == 2


def test_sqlite_registry_round_trip_keeps_ids(tmp_path: Path) -> None:
    database = Database(tmp_path / "registry.db")
    database.initialize()
    first = SourceRegistry(database, seed_mvp=True)
    github = first.find_publisher(slug="github")
    endpoint = first.register_endpoint(
        url="https://status.acme.example/history.rss",
        family=SourceKind.RSS_ATOM,
        created_at="2026-08-01T00:00:00Z",
    )
    first.record_redirect(
        previous_url="https://status.acme.example/history.rss",
        current_url="https://status.acme.example/feed.xml",
        family=SourceKind.RSS_ATOM,
        recorded_at="2026-08-02T00:00:00Z",
    )

    reloaded = SourceRegistry(database, seed_mvp=False)
    assert reloaded.find_publisher(slug="github").publisher_id == github.publisher_id
    assert reloaded.get_endpoint(endpoint.endpoint_id).canonical_url == endpoint.canonical_url
    moved = reloaded.find_duplicate_endpoint(
        "https://status.acme.example/feed.xml",
        family=SourceKind.RSS_ATOM,
    )
    assert moved is not None
    assert moved.redirect_of == endpoint.endpoint_id
    assert reloaded.lineage_for(moved.endpoint_id)
