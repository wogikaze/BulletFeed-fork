from __future__ import annotations

from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlparse

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.database import Database
from app.services.source_catalog import SourceKind
from app.services.source_feed_discover import (
    SITE_FEED_DISCOVER_VERSION,
    discover_feeds_from_site_url,
    extract_alternate_feed_links,
    well_known_feed_urls,
)
from app.services.source_registry import SourceRegistry, canonicalize_url

FIXTURES = Path(__file__).parent / "fixtures" / "feed_discover"
PUBLIC_PEER = "93.184.216.34"
RSS_BODY = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>Notes</title></channel></rss>
"""
JSON_FEED_BODY = b'{"version":"https://jsonfeed.org/version/1.1","title":"Notes","items":[]}'


class _FakeNetworkStream:
    def __init__(self, peer: str) -> None:
        self.peer = peer

    def get_extra_info(self, name: str):
        return (self.peer, 443) if name == "server_addr" else None


class _FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        peer: str = PUBLIC_PEER,
        headers: dict[str, str] | None = None,
        chunks: list[bytes] | None = None,
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {"content-type": "text/html"}
        self.extensions = {"network_stream": _FakeNetworkStream(peer)}
        self._chunks = chunks if chunks is not None else [b"<html/>"]

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def aiter_raw(self):
        for chunk in self._chunks:
            yield chunk


class _ScriptedClient:
    def __init__(self, routes: dict[str, _FakeResponse | list[_FakeResponse] | Exception]) -> None:
        self.routes = {
            url: [item] if isinstance(item, (_FakeResponse, Exception)) else list(item)
            for url, item in routes.items()
        }
        self.calls: list[dict[str, object]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    def stream(self, method: str, url: str, **kwargs):
        self.calls.append({"method": method, "url": url, "headers": kwargs.get("headers", {})})
        items = self.routes.get(url)
        if items is None:
            alt = url.rstrip("/") if url.endswith("/") else f"{url}/"
            items = self.routes.get(alt)
        if items is None and url.endswith("/robots.txt"):
            return _FakeResponse(
                status_code=404,
                headers={"content-type": "text/plain"},
                chunks=[b""],
            )
        if not items:
            path = urlparse(url).path.lower()
            if any(token in path for token in ("feed", "rss", "atom", "index.xml", "news.xml")):
                return _FakeResponse(status_code=404, headers={"content-type": "text/plain"}, chunks=[b""])
            raise AssertionError(f"unexpected request {method} {url}")
        item = items[0] if len(items) == 1 else items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _settings() -> Settings:
    return Settings(web_allowed_hosts="example.com", rss_allowed_hosts="example.com")


def _public_dns():
    return patch(
        "app.services.url_safety.socket.getaddrinfo",
        return_value=[(2, 1, 6, "", (PUBLIC_PEER, 443))],
    )


def _rss_dns():
    return patch(
        "app.services.rss.socket.getaddrinfo",
        return_value=[(2, 1, 6, "", (PUBLIC_PEER, 443))],
    )


def _install_clients(monkeypatch, client: _ScriptedClient) -> None:
    monkeypatch.setattr("app.services.web_snapshots.httpx.AsyncClient", lambda **kwargs: client)
    monkeypatch.setattr(
        "app.services.source_feed_discover.httpx.AsyncClient",
        lambda **kwargs: client,
    )


def _html(name: str, *, url: str) -> _FakeResponse:
    body = (FIXTURES / name).read_bytes()
    return _FakeResponse(headers={"content-type": "text/html; charset=utf-8"}, chunks=[body])


def _feed_response(body: bytes = RSS_BODY, *, content_type: str = "application/rss+xml") -> _FakeResponse:
    return _FakeResponse(headers={"content-type": content_type}, chunks=[body])


def test_extracts_wordpress_hugo_jekyll_ghost_and_json_feed_fixtures() -> None:
    cases = (
        ("wordpress.html", "https://notes.example.com/", SourceKind.RSS_ATOM, "/feed"),
        ("hugo.html", "https://notes.example.com/", SourceKind.RSS_ATOM, "/index.xml"),
        ("jekyll.html", "https://notes.example.com/", SourceKind.RSS_ATOM, "/feed.xml"),
        ("ghost.html", "https://notes.example.com/", SourceKind.RSS_ATOM, "/rss"),
        ("jsonfeed.html", "https://notes.example.com/", SourceKind.JSON_FEED, "/feed.json"),
    )
    for filename, page_url, family, path_token in cases:
        html = (FIXTURES / filename).read_text(encoding="utf-8")
        links = extract_alternate_feed_links(html, page_url=page_url)
        assert links, filename
        assert links[0].family == family
        assert path_token in canonicalize_url(links[0].href)


def test_wordpress_json_api_is_not_treated_as_json_feed() -> None:
    html = (FIXTURES / "wordpress.html").read_text(encoding="utf-8")
    links = extract_alternate_feed_links(html, page_url="https://notes.example.com/")
    hrefs = {canonicalize_url(link.href) for link in links}
    assert canonicalize_url("https://notes.example.com/feed/") in hrefs
    assert not any("wp-json" in href for href in hrefs)


def test_well_known_paths_are_same_origin_and_capped() -> None:
    urls = well_known_feed_urls("https://notes.example.com/blog/", limit=5)
    assert len(urls) == 5
    assert all(canonicalize_url(url).startswith("https://notes.example.com/") for url in urls)
    assert canonicalize_url(urls[0]).endswith("/feed")
    assert len(well_known_feed_urls("https://notes.example.com/blog/", limit=80)) == 16


@pytest.mark.asyncio
async def test_html_alternate_is_preferred_over_generic_web(tmp_path, monkeypatch) -> None:
    web = _ScriptedClient(
        {
            "https://notes.example.com/": _html("hugo.html", url="https://notes.example.com/"),
        }
    )
    _install_clients(monkeypatch, web)
    database = Database(tmp_path / "discover.db")
    database.initialize()
    with _public_dns(), _rss_dns():
        result = await discover_feeds_from_site_url(
            _settings(),
            "https://notes.example.com/",
            database=database,
        )
    assert result.version == SITE_FEED_DISCOVER_VERSION
    assert result.preferred_family == SourceKind.RSS_ATOM.value
    assert len(result.items) == 1
    item = result.items[0]
    assert item.canonical_url == canonicalize_url("https://notes.example.com/index.xml")
    assert item.discovery_method == "html_link_alternate"
    assert item.evidence_eligible is False
    assert item.discovery_only is True
    assert item.actionability == "subscribe"
    assert item.family == SourceKind.RSS_ATOM.value
    assert all(entry.family != SourceKind.GENERIC_WEB.value for entry in result.items)
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) AS c FROM observations").fetchone()["c"] == 0
        assert connection.execute("SELECT COUNT(*) AS c FROM source_sync_subscriptions").fetchone()["c"] == 0


@pytest.mark.asyncio
async def test_no_feed_site_falls_back_to_generic_web(tmp_path, monkeypatch) -> None:
    missing = _FakeResponse(status_code=404, headers={"content-type": "text/plain"}, chunks=[b""])
    web = _ScriptedClient(
        {
            "https://docs.example.com/": _html("no_feed.html", url="https://docs.example.com/"),
            "https://docs.example.com/feed": missing,
            "https://docs.example.com/rss": missing,
            "https://docs.example.com/atom.xml": missing,
            "https://docs.example.com/feed.xml": missing,
            "https://docs.example.com/index.xml": missing,
        }
    )
    _install_clients(monkeypatch, web)
    database = Database(tmp_path / "fallback.db")
    database.initialize()
    with _public_dns(), _rss_dns():
        result = await discover_feeds_from_site_url(
            _settings(),
            "https://docs.example.com/",
            database=database,
        )
    assert result.preferred_family == SourceKind.GENERIC_WEB.value
    assert len(result.items) == 1
    item = result.items[0]
    assert item.family == SourceKind.GENERIC_WEB.value
    assert item.discovery_method == "site_url_fallback"
    assert item.evidence_eligible is False
    assert item.discovery_only is True


@pytest.mark.asyncio
async def test_well_known_path_probe_confirms_feed_without_html_link(tmp_path, monkeypatch) -> None:
    homepage = _html("no_feed.html", url="https://plain.example.com/")
    client = _ScriptedClient(
        {
            "https://plain.example.com/": homepage,
            "https://plain.example.com": homepage,
            "https://plain.example.com/feed": _feed_response(),
            "https://plain.example.com/rss": _FakeResponse(status_code=404),
            "https://plain.example.com/atom.xml": _FakeResponse(status_code=404),
            "https://plain.example.com/feed.xml": _FakeResponse(status_code=404),
            "https://plain.example.com/index.xml": _FakeResponse(status_code=404),
        }
    )
    _install_clients(monkeypatch, client)
    database = Database(tmp_path / "probe.db")
    database.initialize()
    with _public_dns(), _rss_dns():
        result = await discover_feeds_from_site_url(
            _settings(),
            "https://plain.example.com/",
            database=database,
        )
    assert result.preferred_family == SourceKind.RSS_ATOM.value
    assert result.items[0].discovery_method == "well_known_path"
    assert result.items[0].canonical_url == canonicalize_url("https://plain.example.com/feed")
    assert result.items[0].evidence_eligible is False


@pytest.mark.asyncio
async def test_rejects_private_ip_and_credential_url() -> None:
    with patch(
        "app.services.url_safety.socket.getaddrinfo",
        return_value=[(2, 1, 6, "", ("127.0.0.1", 443))],
    ):
        with pytest.raises(HTTPException) as private:
            await discover_feeds_from_site_url(
                _settings(),
                "https://notes.example.com/",
                persist_registry=False,
            )
    assert private.value.status_code == 403
    with pytest.raises(HTTPException) as creds:
        await discover_feeds_from_site_url(
            _settings(),
            "https://user:secret@notes.example.com/",
            persist_registry=False,
        )
    assert creds.value.status_code == 422


@pytest.mark.asyncio
async def test_robots_disallow_fails_closed(monkeypatch) -> None:
    web = _ScriptedClient(
        {
            "https://notes.example.com/robots.txt": _FakeResponse(
                headers={"content-type": "text/plain"},
                chunks=[b"User-agent: *\nDisallow: /\n"],
            )
        }
    )
    _install_clients(monkeypatch, web)
    with _public_dns(), _rss_dns():
        with pytest.raises(HTTPException) as exc_info:
            await discover_feeds_from_site_url(
                _settings(),
                "https://notes.example.com/",
                persist_registry=False,
            )
    assert exc_info.value.status_code == 403
    assert [call["url"] for call in web.calls] == ["https://notes.example.com/robots.txt"]


def test_site_url_to_feed_candidate_to_subscription(database, client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("BULLETFEED_WEB_ALLOWED_HOSTS", "example.com")
    monkeypatch.setenv("BULLETFEED_RSS_ALLOWED_HOSTS", "example.com")
    get_settings.cache_clear()
    web = _ScriptedClient(
        {
            "https://notes.example.com/": _html("wordpress.html", url="https://notes.example.com/"),
        }
    )
    _install_clients(monkeypatch, web)
    session = client.post("/v1/sessions")
    assert session.status_code == 200
    headers = {"Authorization": f"Bearer {session.json()['accessToken']}"}
    with _public_dns(), _rss_dns():
        discovered = client.post(
            "/v1/me/sources/discover",
            headers=headers,
            json={"url": "https://notes.example.com/"},
        )
    assert discovered.status_code == 200
    body = discovered.json()
    assert body["version"] == SITE_FEED_DISCOVER_VERSION
    assert body["preferredFamily"] == "rss_atom"
    assert body["items"][0]["evidenceEligible"] is False
    assert body["items"][0]["discoveryOnly"] is True
    feed_url = body["items"][0]["canonicalUrl"]
    with _rss_dns():
        created = client.post(
            "/v1/me/sources",
            headers=headers,
            json={"kind": "rss_atom", "url": feed_url},
        )
    assert created.status_code == 201
    assert created.json()["kind"] == "rss_atom"
    assert created.json()["canonicalUrl"] == feed_url
    with database.connect() as connection:
        subs = connection.execute("SELECT COUNT(*) AS c FROM source_sync_subscriptions").fetchone()["c"]
        jobs = connection.execute("SELECT COUNT(*) AS c FROM source_sync_jobs").fetchone()["c"]
        observations = connection.execute("SELECT COUNT(*) AS c FROM observations").fetchone()["c"]
    assert subs == 1
    assert jobs == 1
    assert observations == 0
    get_settings.cache_clear()


def test_discover_requires_auth(client: TestClient) -> None:
    response = client.post("/v1/me/sources/discover", json={"url": "https://notes.example.com/"})
    assert response.status_code == 401


def test_gold_includes_blog_generator_family() -> None:
    from app.evaluation.source_discovery_gold import evaluate_source_discovery, load_source_discovery_gold

    gold = load_source_discovery_gold(
        Path(__file__).parent / "gold" / "source_discovery" / "v01" / "cases.json"
    )
    case = next(item for item in gold.cases if item.case_id == "static-site-blogs")
    report = evaluate_source_discovery(gold, registry=SourceRegistry())
    score = next(item for item in report.cases if item.case_id == "static-site-blogs")
    assert "hugo" in " ".join(case.topics).casefold() or "Hugo" in case.topics
    assert score.recall >= case.min_recall
    assert score.precision >= case.min_precision
    assert any("gohugo.io" in url for url in score.hits)
    assert any("jekyllrb.com" in url for url in score.hits)
