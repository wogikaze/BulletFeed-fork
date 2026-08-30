from __future__ import annotations

import socket
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from fastapi import HTTPException

from app.config import Settings
from app.database import Database
from app.services.source_catalog import SourceKind, get_source_policy, source_allows_claim_evidence
from app.services.web_snapshots import (
    WEB_SNAPSHOT_POLL_INTERVAL_SECONDS,
    WEB_SNAPSHOT_RETRY_BASE_SECONDS,
    WEB_SNAPSHOT_SOURCE_TYPE,
    RobotsDecision,
    SnapshotImmutabilityError,
    SnapshotStore,
    WebSnapshot,
    content_hash_for,
    fetch_web_snapshot,
    record_web_snapshot_sync_result,
    referenced_snapshot_ids,
    snapshot_id_for,
    validate_web_url,
    web_snapshot_backoff_seconds,
)

PUBLIC_PEER = "93.184.216.34"
PAGE_URL = "https://docs.example.com/changelog"
FIXTURE = Path(__file__).parent / "fixtures" / "web_snapshots" / "changelog.html"


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
        if items is None and url.endswith("/robots.txt"):
            return _FakeResponse(
                status_code=404,
                headers={"content-type": "text/plain"},
                chunks=[b""],
            )
        if not items:
            raise AssertionError(f"unexpected request {method} {url}")
        item = items[0] if len(items) == 1 else items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _settings(**overrides: object) -> Settings:
    values = {"web_allowed_hosts": "example.com", "max_response_bytes": 1_048_576}
    values.update(overrides)
    return Settings(**values)


def _public_dns():
    return patch(
        "app.services.url_safety.socket.getaddrinfo",
        return_value=[(2, 1, 6, "", (PUBLIC_PEER, 443))],
    )


def _install_client(monkeypatch, client: _ScriptedClient) -> _ScriptedClient:
    monkeypatch.setattr(
        "app.services.web_snapshots.httpx.AsyncClient",
        lambda **kwargs: client,
    )
    return client


def _page_response(body: bytes, *, extra_headers: dict[str, str] | None = None) -> _FakeResponse:
    headers = {"content-type": "text/html; charset=utf-8"}
    if extra_headers:
        headers.update(extra_headers)
    return _FakeResponse(headers=headers, chunks=[body])


def _snapshot(
    *,
    body: bytes = b"<html>v1</html>",
    retrieved_at: str = "2026-08-29T00:00:00Z",
    headers: tuple[tuple[str, str], ...] = (("content-type", "text/html"),),
    canonical_url: str = "https://docs.example.com/changelog",
    etag: str | None = '"v1"',
    last_modified: str | None = "Wed, 20 Aug 2026 10:00:00 GMT",
) -> WebSnapshot:
    digest = content_hash_for(body)
    header_map = {key: value for key, value in headers}
    return WebSnapshot(
        snapshot_id=snapshot_id_for(
            canonical_url=canonical_url,
            content_hash=digest,
            retrieved_at=retrieved_at,
        ),
        canonical_url=canonical_url,
        retrieved_at=retrieved_at,
        content_hash=digest,
        status_code=200,
        headers=headers,
        body=body,
        etag=header_map.get("etag", etag),
        last_modified=header_map.get("last-modified", last_modified),
        robots=RobotsDecision(
            source_url=PAGE_URL,
            robots_url="https://docs.example.com/robots.txt",
            allowed=True,
            reason="robots_missing",
            retrieved_at=retrieved_at,
        ),
        final_url=canonical_url,
    )


def test_generic_web_is_discovery_only_and_not_claim_evidence() -> None:
    policy = get_source_policy(SourceKind.GENERIC_WEB)
    assert policy.discovery_only is True
    assert policy.authoritative is False
    assert source_allows_claim_evidence(SourceKind.GENERIC_WEB.value) is False
    assert source_allows_claim_evidence("generic_html") is False


def test_allowlist_miss_fails_closed() -> None:
    with pytest.raises(HTTPException) as exc_info:
        validate_web_url("https://attacker.example/page", {"docs.example.com"})
    assert exc_info.value.status_code == 403


def test_non_https_fails_closed_outside_tests() -> None:
    with pytest.raises(HTTPException) as exc_info:
        validate_web_url("http://docs.example.com/changelog", {"example.com"})
    assert exc_info.value.status_code == 422


@patch("app.services.url_safety.socket.getaddrinfo")
def test_private_ip_fails_closed(mock_getaddrinfo) -> None:
    mock_getaddrinfo.return_value = [(2, 1, 6, "", ("127.0.0.1", 443))]
    with pytest.raises(HTTPException) as exc_info:
        validate_web_url("https://docs.example.com/changelog", {"example.com"})
    assert exc_info.value.status_code == 403


@patch("app.services.url_safety.socket.getaddrinfo")
def test_unknown_unresolvable_host_fails_closed(mock_getaddrinfo) -> None:
    mock_getaddrinfo.side_effect = socket.gaierror(socket.EAI_NONAME, "name not known")
    with pytest.raises(HTTPException) as exc_info:
        validate_web_url("https://docs.example.com/changelog", {"example.com"})
    assert exc_info.value.status_code == 422


def test_identical_content_shares_hash_and_snapshot_id() -> None:
    body = FIXTURE.read_bytes()
    first = snapshot_id_for(
        canonical_url="https://docs.example.com/changelog",
        content_hash=content_hash_for(body),
        retrieved_at="2026-08-29T00:00:00Z",
    )
    second = snapshot_id_for(
        canonical_url="https://docs.example.com/changelog",
        content_hash=content_hash_for(body),
        retrieved_at="2026-08-30T00:00:00Z",
    )
    assert first == second
    assert first.startswith("snap_")
    assert content_hash_for(body) == content_hash_for(bytes(body))


def test_snapshot_store_is_immutable(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "snaps")
    original = _snapshot()
    stored = store.put(original)
    assert stored.body == original.body

    mutated = replace(original, headers=(("content-type", "text/plain"),), etag='"mutated"')
    with pytest.raises(SnapshotImmutabilityError):
        store.put(mutated)

    reloaded = store.get(original.snapshot_id)
    assert reloaded is not None
    assert reloaded.body == original.body
    assert reloaded.headers == original.headers
    assert reloaded.etag == '"v1"'
    assert store.list_ids() == (original.snapshot_id,)


def test_snapshot_gc_retains_referenced_and_expired_snapshots(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "snaps")
    referenced = _snapshot(body=b"<html>referenced</html>", retrieved_at="2025-01-01T00:00:00Z")
    expired = _snapshot(body=b"<html>expired</html>", retrieved_at="2025-01-02T00:00:00Z")
    recent = _snapshot(body=b"<html>recent</html>", retrieved_at="2026-08-29T00:00:00Z")
    for snapshot in (referenced, expired, recent):
        store.put(snapshot)

    result = store.garbage_collect(
        referenced_ids={referenced.snapshot_id},
        retention_days=30,
        now=datetime(2026, 8, 30, tzinfo=UTC),
    )

    assert result.scanned_count == 3
    assert result.deleted_ids == (expired.snapshot_id,)
    assert result.retained_referenced_ids == (referenced.snapshot_id,)
    assert set(store.list_ids()) == {referenced.snapshot_id, recent.snapshot_id}


def test_snapshot_gc_capacity_preserves_referenced_snapshot(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "snaps")
    referenced = _snapshot(body=b"r" * 100, retrieved_at="2026-08-01T00:00:00Z")
    removable = _snapshot(body=b"x" * 100, retrieved_at="2026-08-02T00:00:00Z")
    store.put(referenced)
    store.put(removable)
    before = store.storage_stats()

    result = store.garbage_collect(
        referenced_ids={referenced.snapshot_id},
        retention_days=365,
        max_bytes=before.metadata_bytes + 100,
        now=datetime(2026, 8, 30, tzinfo=UTC),
    )

    assert result.deleted_ids == (removable.snapshot_id,)
    assert result.retained_referenced_ids == (referenced.snapshot_id,)
    assert store.get(referenced.snapshot_id) is not None


def test_referenced_snapshot_ids_are_read_from_web_observations(tmp_path: Path) -> None:
    database = Database(tmp_path / "references.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO observations (
                id, source_type, source_key, source_observation_id,
                payload_hash, payload_json, original_url, retrieved_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "obs_snapshot_ref",
                WEB_SNAPSHOT_SOURCE_TYPE,
                "https://docs.example.com/changelog",
                "snapshot-ref",
                "hash",
                '{"left_snapshot_id":"snap_left","nested":{"right_snapshot_id":"snap_right"}}',
                "https://docs.example.com/changelog",
                "2026-08-30T00:00:00Z",
            ),
        )

    assert referenced_snapshot_ids(database) == frozenset({"snap_left", "snap_right"})


@pytest.mark.asyncio
async def test_fetch_rejects_allowlist_miss_before_http(tmp_path: Path, monkeypatch) -> None:
    client = _install_client(monkeypatch, _ScriptedClient({}))
    with pytest.raises(HTTPException) as exc_info:
        await fetch_web_snapshot(
            _settings(web_allowed_hosts="official.example"),
            PAGE_URL,
            store=SnapshotStore(tmp_path / "snaps"),
        )
    assert exc_info.value.status_code == 403
    assert client.calls == []


@pytest.mark.asyncio
async def test_fetch_rejects_private_ip_before_http(tmp_path: Path, monkeypatch) -> None:
    client = _install_client(monkeypatch, _ScriptedClient({}))
    with patch(
        "app.services.url_safety.socket.getaddrinfo",
        return_value=[(2, 1, 6, "", ("10.0.0.5", 443))],
    ):
        with pytest.raises(HTTPException) as exc_info:
            await fetch_web_snapshot(
                _settings(),
                PAGE_URL,
                store=SnapshotStore(tmp_path / "snaps"),
            )
    assert exc_info.value.status_code == 403
    assert client.calls == []


@pytest.mark.asyncio
async def test_fetch_bounds_redirects(tmp_path: Path, monkeypatch) -> None:
    redirect = _FakeResponse(
        status_code=302,
        headers={"location": "https://docs.example.com/changelog"},
        chunks=[b""],
    )
    client = _install_client(
        monkeypatch,
        _ScriptedClient({PAGE_URL: redirect}),
    )
    with _public_dns():
        with pytest.raises(HTTPException) as exc_info:
            await fetch_web_snapshot(
                _settings(),
                PAGE_URL,
                store=SnapshotStore(tmp_path / "snaps"),
                check_robots=False,
            )
    assert exc_info.value.status_code == 502
    page_calls = [call for call in client.calls if call["url"] == PAGE_URL]
    assert len(page_calls) == 4


@pytest.mark.asyncio
async def test_fetch_rejects_dns_rebinding_peer(tmp_path: Path, monkeypatch) -> None:
    client = _install_client(
        monkeypatch,
        _ScriptedClient({PAGE_URL: _FakeResponse(peer="127.0.0.1")}),
    )
    with _public_dns():
        with pytest.raises(HTTPException) as exc_info:
            await fetch_web_snapshot(
                _settings(),
                PAGE_URL,
                store=SnapshotStore(tmp_path / "snaps"),
                check_robots=False,
            )
    assert exc_info.value.status_code == 403
    assert client.calls


@pytest.mark.asyncio
async def test_fetch_rejects_oversize_body(tmp_path: Path, monkeypatch) -> None:
    _install_client(
        monkeypatch,
        _ScriptedClient({PAGE_URL: _FakeResponse(chunks=[b"123", b"456"])}),
    )
    with _public_dns():
        with pytest.raises(HTTPException) as exc_info:
            await fetch_web_snapshot(
                _settings(max_response_bytes=4),
                PAGE_URL,
                store=SnapshotStore(tmp_path / "snaps"),
                check_robots=False,
            )
    assert exc_info.value.status_code == 413


@pytest.mark.asyncio
async def test_fetch_times_out(tmp_path: Path, monkeypatch) -> None:
    _install_client(
        monkeypatch,
        _ScriptedClient({PAGE_URL: httpx.TimeoutException("timed out")}),
    )
    with _public_dns():
        with pytest.raises(HTTPException) as exc_info:
            await fetch_web_snapshot(
                _settings(request_timeout_seconds=0.01),
                PAGE_URL,
                store=SnapshotStore(tmp_path / "snaps"),
                check_robots=False,
            )
    assert exc_info.value.status_code == 504


@pytest.mark.asyncio
async def test_fetch_stores_immutable_snapshot_and_reuses_identical_content(
    tmp_path: Path,
    monkeypatch,
) -> None:
    body = FIXTURE.read_bytes()
    client = _install_client(
        monkeypatch,
        _ScriptedClient(
            {
                PAGE_URL: _page_response(
                    body,
                    extra_headers={"etag": '"chg-1"', "last-modified": "Wed, 20 Aug 2026 10:00:00 GMT"},
                )
            }
        ),
    )
    store = SnapshotStore(tmp_path / "snaps")
    settings = _settings()
    with _public_dns():
        first = await fetch_web_snapshot(
            settings,
            PAGE_URL,
            store=store,
            retrieved_at="2026-08-29T08:00:00Z",
        )
        second = await fetch_web_snapshot(
            settings,
            PAGE_URL,
            store=store,
            retrieved_at="2026-08-29T09:00:00Z",
        )
    assert first.content_hash == content_hash_for(body)
    assert first.content_hash == second.content_hash
    assert first.snapshot_id == second.snapshot_id
    assert first.retrieved_at == "2026-08-29T08:00:00Z"
    assert second.retrieved_at == first.retrieved_at
    assert store.list_ids() == (first.snapshot_id,)
    reloaded = store.get(first.snapshot_id)
    assert reloaded is not None
    assert reloaded.body == body
    assert first.robots.reason == "robots_missing"
    assert any(str(call["url"]).endswith("/robots.txt") for call in client.calls)


@pytest.mark.asyncio
async def test_conditional_304_does_not_create_a_new_version(tmp_path: Path, monkeypatch) -> None:
    body = FIXTURE.read_bytes()
    store = SnapshotStore(tmp_path / "snaps")
    first = store.put(
        _snapshot(
            body=body,
            headers=(
                ("content-type", "text/html; charset=utf-8"),
                ("etag", '"chg-1"'),
                ("last-modified", "Wed, 20 Aug 2026 10:00:00 GMT"),
            ),
        )
    )
    client = _install_client(
        monkeypatch,
        _ScriptedClient(
            {
                PAGE_URL: _FakeResponse(
                    status_code=304,
                    headers={"etag": '"chg-1"'},
                    chunks=[b""],
                )
            }
        ),
    )
    with _public_dns():
        again = await fetch_web_snapshot(
            _settings(),
            PAGE_URL,
            store=store,
            previous=first,
            retrieved_at="2026-08-29T12:00:00Z",
            check_robots=False,
        )
    assert again.snapshot_id == first.snapshot_id
    assert again.not_modified is True
    assert again.body == body
    assert store.list_ids() == (first.snapshot_id,)
    request_headers = client.calls[0]["headers"]
    assert request_headers["If-None-Match"] == '"chg-1"'
    assert request_headers["If-Modified-Since"] == "Wed, 20 Aug 2026 10:00:00 GMT"


@pytest.mark.asyncio
async def test_robots_disallow_fails_closed(tmp_path: Path, monkeypatch) -> None:
    client = _install_client(
        monkeypatch,
        _ScriptedClient(
            {
                "https://docs.example.com/robots.txt": _FakeResponse(
                    headers={"content-type": "text/plain"},
                    chunks=[b"User-agent: *\nDisallow: /\n"],
                ),
                PAGE_URL: _page_response(FIXTURE.read_bytes()),
            }
        ),
    )
    with _public_dns():
        with pytest.raises(HTTPException) as exc_info:
            await fetch_web_snapshot(
                _settings(),
                PAGE_URL,
                store=SnapshotStore(tmp_path / "snaps"),
            )
    assert exc_info.value.status_code == 403
    assert [call["url"] for call in client.calls] == ["https://docs.example.com/robots.txt"]


def test_retry_backoff_matches_persistent_source_scheduler(tmp_path: Path) -> None:
    database = Database(tmp_path / "schedule.db")
    database.initialize()
    now = 1_800_000_000
    record_web_snapshot_sync_result(database, PAGE_URL, now=now)
    record_web_snapshot_sync_result(database, PAGE_URL, now=now + 1, error="timeout")
    record_web_snapshot_sync_result(database, PAGE_URL, now=now + 2, error="timeout")

    with database.connect() as connection:
        job = connection.execute(
            """
            SELECT source_type, source_key, failure_count, next_run_at, last_error
            FROM source_sync_jobs
            WHERE source_type = ?
            """,
            (WEB_SNAPSHOT_SOURCE_TYPE,),
        ).fetchone()
        observations = connection.execute("SELECT COUNT(*) AS count FROM observations").fetchone()["count"]

    assert job["source_type"] == "generic_web"
    assert job["failure_count"] == 2
    assert job["next_run_at"] == now + 2 + web_snapshot_backoff_seconds(2)
    assert job["next_run_at"] == now + 2 + (WEB_SNAPSHOT_RETRY_BASE_SECONDS * 2)
    assert observations == 0
    assert web_snapshot_backoff_seconds(0) == WEB_SNAPSHOT_POLL_INTERVAL_SECONDS


def test_empty_web_allowlist_disables_fetch() -> None:
    settings = Settings(web_allowed_hosts="")
    assert settings.web_hosts == set()
