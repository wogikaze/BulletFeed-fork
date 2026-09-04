from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.database import Database
from app.services.source_feed_discover import SiteFeedCandidate, SiteFeedDiscoverResult
from app.services.source_subscriptions import add_subscription_user
from app.services.user_source_grants import (
    active_subscription_has_discovery_grant,
    record_user_source_discovery_grants,
    settings_for_active_source,
    settings_for_site_discovery,
    settings_for_user_subscription,
)

PUBLIC_PEER = "93.184.216.34"
SOURCE_URL = "https://notes.example.com/feed"


def _candidate() -> SiteFeedCandidate:
    return SiteFeedCandidate(
        candidate_id="ep_discovered",
        endpoint_id="ep_discovered",
        canonical_url=SOURCE_URL,
        family="rss_atom",
        discovery_method="html_link_alternate",
        discovery_provenance="website_feed",
        title="Notes",
        preferred=True,
        evidence_eligible=False,
        discovery_only=True,
        actionability="subscribe",
        verification_status="unverified",
        authority_status="unknown",
        publisher_slug="notes.example.com",
        publisher_display_name="notes.example.com",
        site_url="https://notes.example.com/",
        explanation="discovered",
    )


def test_grant_only_expands_settings_for_the_user_that_discovered_source(tmp_path) -> None:
    database = Database(tmp_path / "grants.db")
    database.initialize()
    settings = Settings(rss_allowed_hosts="", web_allowed_hosts="")

    untouched = settings_for_user_subscription(
        database,
        settings,
        user_id="other-user",
        source_type="rss_atom",
        url=SOURCE_URL,
    )
    assert untouched.rss_hosts == set()

    record_user_source_discovery_grants(
        database,
        user_id="user-1",
        sources=(("rss_atom", SOURCE_URL),),
        now=100,
    )
    granted = settings_for_user_subscription(
        database,
        settings,
        user_id="user-1",
        source_type="rss_atom",
        url=SOURCE_URL,
    )
    assert granted.rss_hosts == {"notes.example.com"}
    assert granted.web_hosts == {"notes.example.com"}


def test_worker_grant_requires_an_active_subscription_owner(tmp_path) -> None:
    database = Database(tmp_path / "worker-grants.db")
    database.initialize()
    settings = Settings(rss_allowed_hosts="", web_allowed_hosts="")
    record_user_source_discovery_grants(
        database,
        user_id="user-1",
        sources=(("rss_atom", SOURCE_URL),),
        now=100,
    )
    assert active_subscription_has_discovery_grant(
        database,
        source_type="rss_atom",
        source_key=SOURCE_URL,
    ) is False

    add_subscription_user(
        database,
        source_type="rss_atom",
        source_key=SOURCE_URL,
        user_id="user-1",
    )
    assert active_subscription_has_discovery_grant(
        database,
        source_type="rss_atom",
        source_key=SOURCE_URL,
    ) is True
    effective = settings_for_active_source(
        database,
        settings,
        source_type="rss_atom",
        source_key=SOURCE_URL,
    )
    assert effective.rss_hosts == {"notes.example.com"}


def test_site_discovery_admits_only_the_submitted_public_host() -> None:
    effective = settings_for_site_discovery(
        Settings(rss_allowed_hosts="feeds.example.org", web_allowed_hosts="docs.example.org"),
        "https://notes.example.com/blog",
    )
    assert effective.rss_hosts == {"feeds.example.org", "notes.example.com"}
    assert effective.web_hosts == {"docs.example.org", "notes.example.com"}


def test_default_config_requires_discovery_before_arbitrary_feed_subscription(
    database: Database,
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setenv("BULLETFEED_WEB_ALLOWED_HOSTS", "")
    monkeypatch.setenv("BULLETFEED_RSS_ALLOWED_HOSTS", "")
    get_settings.cache_clear()
    session = client.post("/v1/sessions")
    assert session.status_code == 200
    headers = {"Authorization": f"Bearer {session.json()['accessToken']}"}

    blocked = client.post(
        "/v1/me/sources",
        headers=headers,
        json={"kind": "rss_atom", "url": SOURCE_URL},
    )
    assert blocked.status_code == 403

    async def fake_discover(*args, **kwargs):
        del args, kwargs
        return SiteFeedDiscoverResult(
            version="site-feed-discover-v1",
            site_url="https://notes.example.com/",
            canonical_site_url="https://notes.example.com/",
            preferred_family="rss_atom",
            items=(_candidate(),),
        )

    monkeypatch.setattr(
        "app.routers.source_discovery.discover_feeds_from_site_url",
        fake_discover,
    )
    discovered = client.post(
        "/v1/me/sources/discover",
        headers=headers,
        json={"url": "https://notes.example.com/"},
    )
    assert discovered.status_code == 200
    assert discovered.json()["items"][0]["evidenceEligible"] is False

    with patch(
        "app.services.rss.socket.getaddrinfo",
        return_value=[(2, 1, 6, "", (PUBLIC_PEER, 443))],
    ):
        created = client.post(
            "/v1/me/sources",
            headers=headers,
            json={"kind": "rss_atom", "url": SOURCE_URL},
        )
    assert created.status_code == 201
    assert created.json()["canonicalUrl"] == SOURCE_URL

    with database.connect() as connection:
        observations = connection.execute("SELECT COUNT(*) AS c FROM observations").fetchone()["c"]
        grants = connection.execute(
            "SELECT COUNT(*) AS c FROM user_source_discovery_grants"
        ).fetchone()["c"]
    assert observations == 0
    assert grants == 1
    get_settings.cache_clear()
