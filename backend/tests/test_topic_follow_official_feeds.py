from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import app.sync_worker as sync_worker
from app.config import Settings
from app.database import Database
from app.db.topic_catalog import canonical_topic, install_topic_catalog
from app.services.rss import validate_feed_url
from app.services.rss_pipeline import ingest_feed_events
from app.services.source_discovery_seeds import official_subscribe_seeds_for_topic
from app.services.source_registry import canonicalize_url
from app.stores.me_store import MeStore
from app.sync_worker import WatchSyncWorker


def test_llvm_is_in_topic_catalog() -> None:
    topic = canonical_topic("LLVM")
    assert topic is not None
    assert topic[0] == "LLVM"


def test_official_seeds_for_rust_and_llvm_include_rss() -> None:
    rust = official_subscribe_seeds_for_topic("Rust")
    llvm = official_subscribe_seeds_for_topic("LLVM")
    rust_urls = {canonicalize_url(seed.url) for seed in rust}
    llvm_urls = {canonicalize_url(seed.url) for seed in llvm}
    assert canonicalize_url("https://blog.rust-lang.org/feed.xml") in rust_urls
    assert canonicalize_url("https://this-week-in-rust.org/rss.xml") in rust_urls
    assert canonicalize_url("https://blog.llvm.org/feed.xml") in llvm_urls


@patch("app.services.rss.socket.getaddrinfo")
def test_curated_official_feed_is_allowed_without_env_host(mock_getaddrinfo) -> None:
    mock_getaddrinfo.return_value = [(2, 1, 6, "", ("93.184.216.34", 443))]
    url = "https://blog.rust-lang.org/feed.xml"
    assert validate_feed_url(url, set()) == url


def test_unlisted_host_still_blocked() -> None:
    with patch("app.services.rss.socket.getaddrinfo") as mock_getaddrinfo:
        mock_getaddrinfo.return_value = [(2, 1, 6, "", ("93.184.216.34", 443))]
        try:
            validate_feed_url("https://attacker.example/feed.xml", set())
        except HTTPException as exc:
            assert exc.status_code == 403
        else:
            raise AssertionError("expected allowlist rejection")


def test_following_rust_and_llvm_subscribes_official_feeds(tmp_path: Path) -> None:
    database = Database(tmp_path / "topics.db")
    database.initialize()
    install_topic_catalog(database)
    with database.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES (?, 0)", ("user-rust",))
    store = MeStore(database)
    store.add_topic("user-rust", "Rust", "technology")
    store.add_topic("user-rust", "LLVM", "technology")

    with database.connect() as connection:
        urls = {
            row["source_key"]
            for row in connection.execute(
                """
                SELECT source_key FROM source_sync_subscription_users
                WHERE user_id = ? AND source_type = 'rss_atom'
                """,
                ("user-rust",),
            )
        }
        jobs = connection.execute(
            "SELECT COUNT(*) AS count FROM source_sync_jobs WHERE source_type = 'rss_atom'"
        ).fetchone()["count"]
        observations = connection.execute("SELECT COUNT(*) AS count FROM observations").fetchone()["count"]
    assert canonicalize_url("https://blog.rust-lang.org/feed.xml") in urls
    assert canonicalize_url("https://blog.llvm.org/feed.xml") in urls
    assert jobs >= 2
    assert observations == 0


@pytest.mark.asyncio
async def test_following_rust_then_sync_projects_feed_items(tmp_path: Path, monkeypatch) -> None:
    database = Database(tmp_path / "rust-feed.db")
    database.initialize()
    install_topic_catalog(database)
    with database.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES (?, 0)", ("user-rust",))
    MeStore(database).add_topic("user-rust", "Rust", "technology")

    async def fake_crawl(settings, db, *, url, retrieved_at):
        del settings
        preview = {
            "title": "Rust Blog",
            "source_url": url,
            "items": [
                {
                    "title": "Announcing Rust 1.90.0",
                    "link": f"{url.rstrip('/')}/2026-09-01-1.90.0",
                    "published": "2026-09-01T00:00:00Z",
                    "updated": "2026-09-01T00:00:00Z",
                    "summary": "The Rust team is happy to announce a new version of Rust.",
                }
            ],
        }
        return ingest_feed_events(db, preview=preview, retrieved_at=retrieved_at)

    monkeypatch.setattr(sync_worker, "crawl_feed_events", fake_crawl)
    settings = Settings(database_path=database.path, embed_source_sync_worker=False)
    summary = await WatchSyncWorker(settings, database, batch_size=10).run_once(now=1_800_000_000)
    assert summary.succeeded >= 1
    with database.connect() as connection:
        items = connection.execute(
            """
            SELECT title, relation_level
            FROM feed_items
            WHERE user_id = ?
            """,
            ("user-rust",),
        ).fetchall()
    assert items
    assert any("Rust" in row["title"] for row in items)
    assert any(row["relation_level"] in {"direct", "adjacent"} for row in items)


def test_topic_search_finds_llvm(
    client: TestClient, auth_headers: dict[str, str], database: Database
) -> None:
    install_topic_catalog(database)
    search = client.get("/v1/topics/search", headers=auth_headers, params={"q": "llvm"})
    assert search.status_code == 200
    assert any(item["name"] == "LLVM" for item in search.json()["items"])


def test_feed_backfills_official_feeds_for_existing_topics(
    client: TestClient,
    auth_headers: dict[str, str],
    database: Database,
) -> None:
    install_topic_catalog(database)
    session = client.post("/v1/sessions")
    user_id = session.json()["userId"]
    token = session.json()["accessToken"]
    headers = {"Authorization": f"Bearer {token}"}
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO topics (id, user_id, name, type, priority, sort_order, created_at)
            VALUES ('topic_rust_existing', ?, 'Rust', 'technology', 'normal', 0, 0)
            """,
            (user_id,),
        )
    listed = client.get("/v1/feed", headers=headers, params={"limit": 10})
    assert listed.status_code == 200
    with database.connect() as connection:
        urls = {
            row["source_key"]
            for row in connection.execute(
                """
                SELECT source_key FROM source_sync_subscription_users
                WHERE user_id = ? AND source_type = 'rss_atom'
                """,
                (user_id,),
            )
        }
    assert canonicalize_url("https://blog.rust-lang.org/feed.xml") in urls
