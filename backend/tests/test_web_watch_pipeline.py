from __future__ import annotations

import time
from pathlib import Path

import pytest
from test_web_claims import PAGE_URL, V1_SECTIONS, _page, _price_sections
from test_web_snapshots import _FakeResponse, _install_client, _public_dns, _ScriptedClient

from app.config import Settings
from app.database import Database
from app.services.source_catalog import SourceKind
from app.services.source_registry import SourceRegistry
from app.services.source_subscriptions import add_user_source_subscription
from app.services.web_watch_pipeline import crawl_web_watch
from app.sync_worker import WatchSyncWorker


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        web_allowed_hosts="docs.example.com",
        database_path=tmp_path / "watch.db",
    )


def _user(database: Database, user_id: str = "usr_web_watch") -> str:
    with database.connect() as connection:
        connection.execute("INSERT OR IGNORE INTO users (id, created_at) VALUES (?, 0)", (user_id,))
        connection.commit()
    return user_id


@pytest.mark.asyncio
async def test_generic_web_subscription_worker_is_idempotent_and_discovery_only(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = _settings(tmp_path)
    database = Database(settings.database_path)
    database.initialize()
    user_id = _user(database)
    with _public_dns():
        add_user_source_subscription(
            database,
            settings,
            user_id=user_id,
            kind="generic_web",
            url=PAGE_URL,
        )
    with database.connect() as connection:
        job = connection.execute(
            "SELECT source_type, source_key FROM source_sync_jobs WHERE source_type = 'generic_web'"
        ).fetchone()
    assert job is not None
    assert job["source_key"] == PAGE_URL

    v1 = _page(sections=V1_SECTIONS)
    v2 = _page(sections=_price_sections("$12"))
    client = _install_client(
        monkeypatch,
        _ScriptedClient(
            {
                "https://docs.example.com/robots.txt": _FakeResponse(
                    headers={"content-type": "text/plain"},
                    chunks=[b"User-agent: *\nAllow: /\n"],
                ),
                PAGE_URL: [
                    _FakeResponse(chunks=[v1]),
                    _FakeResponse(chunks=[v2]),
                    _FakeResponse(status_code=304, headers={"etag": '"v2"'}),
                ],
            }
        ),
    )
    worker = WatchSyncWorker(settings, database, batch_size=10)
    started = int(time.time())
    with _public_dns():
        first = await worker.run_once(now=started)
        second = await worker.run_once(now=started + 400)
        third = await worker.run_once(now=started + 800)

    assert first.succeeded == 1
    assert second.succeeded == 1
    assert third.succeeded == 1
    assert [call["url"] for call in client.calls if call["url"] == PAGE_URL]

    with database.connect() as connection:
        observations = connection.execute("SELECT COUNT(*) AS count FROM observations").fetchone()["count"]
        claims = connection.execute("SELECT COUNT(*) AS count FROM state_claims").fetchone()["count"]
        source_types = {
            row["source_type"]
            for row in connection.execute("SELECT DISTINCT source_type FROM observations")
        }
    assert observations >= 1
    assert claims == 0
    assert source_types == {SourceKind.GENERIC_WEB.value}


@pytest.mark.asyncio
async def test_official_web_watch_reaches_claim_and_feed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = _settings(tmp_path)
    database = Database(settings.database_path)
    database.initialize()
    user_id = _user(database)
    registry = SourceRegistry(database, seed_mvp=False)
    registry.register_publisher(
        slug="acme",
        display_name="Acme",
        homepage_url="https://docs.example.com",
    )
    registry.register_endpoint(
        url=PAGE_URL,
        family=SourceKind.OFFICIAL_CHANGELOG.value,
        publisher_slug="acme",
    )
    with _public_dns():
        add_user_source_subscription(
            database,
            settings,
            user_id=user_id,
            kind="generic_web",
            url=PAGE_URL,
            registry=registry,
        )
    v1 = _page(sections=V1_SECTIONS)
    v2 = _page(sections=_price_sections("$12"))
    _install_client(
        monkeypatch,
        _ScriptedClient(
            {
                "https://docs.example.com/robots.txt": _FakeResponse(
                    headers={"content-type": "text/plain"},
                    chunks=[b"User-agent: *\nAllow: /\n"],
                ),
                PAGE_URL: [
                    _FakeResponse(chunks=[v1]),
                    _FakeResponse(chunks=[v2]),
                ],
            }
        ),
    )
    with _public_dns():
        first = await crawl_web_watch(
            settings,
            database,
            url=PAGE_URL,
            retrieved_at="2026-08-30T00:00:00Z",
            registry=registry,
        )
        second = await crawl_web_watch(
            settings,
            database,
            url=PAGE_URL,
            retrieved_at="2026-08-30T01:00:00Z",
            registry=registry,
        )
    assert first.ingest is None
    assert second.ingest is not None
    assert second.ingest.claim_eligible is True
    assert second.ingest.claims
    assert second.ingest.event_ids
    with database.connect() as connection:
        feed = connection.execute(
            "SELECT COUNT(*) AS count FROM feed_items WHERE user_id = ?",
            (user_id,),
        ).fetchone()["count"]
    assert feed >= 1
