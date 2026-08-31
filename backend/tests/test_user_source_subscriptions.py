import time
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import Database
from app.main import app
from app.services.source_catalog import SourceKind
from app.services.source_registry import SourceRegistry, canonicalize_url, endpoint_id
from app.services.source_subscriptions import statuspage_canonical_url
from app.sync_worker import WatchSyncWorker


def _auth_headers(client: TestClient) -> dict[str, str]:
    session = client.post("/v1/sessions")
    assert session.status_code == 200
    return {"Authorization": f"Bearer {session.json()['accessToken']}"}


def _enable_feed_hosts(monkeypatch, hosts: str = "example.com") -> None:
    monkeypatch.setenv("BULLETFEED_RSS_ALLOWED_HOSTS", hosts)
    get_settings.cache_clear()


def _public_dns():
    return patch(
        "app.services.rss.socket.getaddrinfo",
        return_value=[(2, 1, 6, "", ("93.184.216.34", 443))],
    )


def _count_jobs(database: Database, *, source_type: str | None = None, source_key: str | None = None) -> int:
    with database.connect() as connection:
        if source_type is None:
            row = connection.execute("SELECT COUNT(*) AS count FROM source_sync_jobs").fetchone()
            return int(row["count"])
        return int(
            connection.execute(
                """
                SELECT COUNT(*) AS count FROM source_sync_jobs
                WHERE source_type = ? AND source_key = ?
                """,
                (source_type, source_key),
            ).fetchone()["count"]
        )


def _count_subscriptions(database: Database) -> int:
    with database.connect() as connection:
        return int(
            connection.execute("SELECT COUNT(*) AS count FROM source_sync_subscriptions").fetchone()["count"]
        )


def _count_subscription_users(
    database: Database,
    *,
    source_type: str | None = None,
    source_key: str | None = None,
) -> int:
    with database.connect() as connection:
        if source_type is None:
            return int(
                connection.execute("SELECT COUNT(*) AS count FROM source_sync_subscription_users").fetchone()[
                    "count"
                ]
            )
        return int(
            connection.execute(
                """
                SELECT COUNT(*) AS count FROM source_sync_subscription_users
                WHERE source_type = ? AND source_key = ?
                """,
                (source_type, source_key),
            ).fetchone()["count"]
        )


def _insert_observation(database: Database, *, source_type: str, source_key: str) -> None:
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO observations (
                id, source_type, source_key, source_observation_id,
                payload_hash, payload_json, original_url, retrieved_at
            ) VALUES (?, ?, ?, 'obs-1', 'hash', '{}', ?, '2026-08-29T00:00:00Z')
            """,
            ("obs_keep", source_type, source_key, source_key),
        )


def test_source_subscription_routes_require_auth(client: TestClient) -> None:
    assert client.get("/v1/me/sources").status_code == 401
    assert client.post("/v1/me/sources", json={"kind": "statuspage", "pageId": "abcd1234"}).status_code == 401
    assert client.delete("/v1/me/sources/ep_missing").status_code == 401


def test_add_list_and_remove_statuspage_subscription(
    client: TestClient,
    database: Database,
    auth_headers: dict[str, str],
) -> None:
    created = client.post(
        "/v1/me/sources",
        headers=auth_headers,
        json={"kind": "statuspage", "pageId": "abcd1234"},
    )
    assert created.status_code == 201
    body = created.json()
    expected_id = endpoint_id(url=statuspage_canonical_url("abcd1234"), family=SourceKind.STATUSPAGE)
    assert body["id"] == expected_id
    assert body["kind"] == "statuspage"
    assert body["pageId"] == "abcd1234"
    assert body["canonicalUrl"] == statuspage_canonical_url("abcd1234")
    assert body["status"]["selected"] is True
    assert body["status"]["state"] == "pending"
    assert "sourceKey" not in body

    listed = client.get("/v1/me/sources", headers=auth_headers)
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [expected_id]

    with database.connect() as connection:
        subscription = connection.execute(
            """
            SELECT selected FROM source_sync_subscriptions
            WHERE source_type = 'statuspage' AND source_key = 'abcd1234'
            """
        ).fetchone()
        job = connection.execute(
            """
            SELECT source_type, source_key FROM source_sync_jobs
            WHERE source_type = 'statuspage' AND source_key = 'abcd1234'
            """
        ).fetchone()
    assert subscription["selected"] == 1
    assert tuple(job) == ("statuspage", "abcd1234")

    removed = client.delete(f"/v1/me/sources/{expected_id}", headers=auth_headers)
    assert removed.status_code == 204
    assert client.get("/v1/me/sources", headers=auth_headers).json()["items"] == []
    assert client.delete(f"/v1/me/sources/{expected_id}", headers=auth_headers).status_code == 404


def test_statuspage_url_and_page_id_are_the_same_canonical_subscription(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    first = client.post(
        "/v1/me/sources",
        headers=auth_headers,
        json={"kind": "statuspage", "url": "https://Abcd1234.statuspage.io/api/v2/summary.json"},
    )
    second = client.post(
        "/v1/me/sources",
        headers=auth_headers,
        json={"kind": "statuspage", "pageId": "abcd1234"},
    )
    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    listed = client.get("/v1/me/sources", headers=auth_headers).json()["items"]
    assert len(listed) == 1


def test_duplicate_canonical_feed_add_is_idempotent(
    client: TestClient,
    database: Database,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    _enable_feed_hosts(monkeypatch)
    with _public_dns():
        first = client.post(
            "/v1/me/sources",
            headers=auth_headers,
            json={"kind": "rss_atom", "url": "https://news.example.com/feed.xml"},
        )
        second = client.post(
            "/v1/me/sources",
            headers=auth_headers,
            json={"kind": "rss_atom", "url": "https://www.news.example.com/feed.xml?utm_campaign=x"},
        )
    assert first.status_code == 201
    assert second.status_code == 200
    canonical = canonicalize_url("https://news.example.com/feed.xml")
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["canonicalUrl"] == canonical
    assert (
        _count_subscription_users(database, source_type="rss_atom", source_key=canonical) == 1
    )
    assert _count_jobs(database, source_type="rss_atom", source_key=canonical) == 1


def test_add_rss_and_json_feed_subscriptions(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    _enable_feed_hosts(monkeypatch)
    with _public_dns():
        rss = client.post(
            "/v1/me/sources",
            headers=auth_headers,
            json={"kind": "rss_atom", "url": "https://news.example.com/feed.xml"},
        )
        json_feed = client.post(
            "/v1/me/sources",
            headers=auth_headers,
            json={"kind": "json_feed", "url": "https://news.example.com/feed.json"},
        )
    assert rss.status_code == 201
    assert json_feed.status_code == 201
    assert rss.json()["id"] != json_feed.json()["id"]
    kinds = {item["kind"] for item in client.get("/v1/me/sources", headers=auth_headers).json()["items"]}
    assert kinds == {"rss_atom", "json_feed"}


def test_generic_web_subscription_round_trips_through_api(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    monkeypatch.setenv("BULLETFEED_WEB_ALLOWED_HOSTS", "docs.example.com")
    get_settings.cache_clear()
    url = "https://docs.example.com/changelog"
    with _public_dns():
        created = client.post(
            "/v1/me/sources",
            headers=auth_headers,
            json={"kind": "generic_web", "url": url},
        )
    assert created.status_code == 201
    assert created.json()["kind"] == "generic_web"
    assert created.json()["canonicalUrl"] == url
    listed = client.get("/v1/me/sources", headers=auth_headers)
    assert listed.status_code == 200
    assert [item["kind"] for item in listed.json()["items"]] == ["generic_web"]


def test_remove_and_readd_reschedules_without_deleting_observations(
    client: TestClient,
    database: Database,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    _enable_feed_hosts(monkeypatch)
    url = "https://news.example.com/feed.xml"
    with _public_dns():
        created = client.post("/v1/me/sources", headers=auth_headers, json={"kind": "rss_atom", "url": url})
    assert created.status_code == 201
    canonical = created.json()["canonicalUrl"]
    subscription_id = created.json()["id"]
    _insert_observation(database, source_type="rss_atom", source_key=canonical)

    removed = client.delete(f"/v1/me/sources/{subscription_id}", headers=auth_headers)
    assert removed.status_code == 204
    with database.connect() as connection:
        selected = connection.execute(
            """
            SELECT selected FROM source_sync_subscriptions
            WHERE source_type = 'rss_atom' AND source_key = ?
            """,
            (canonical,),
        ).fetchone()["selected"]
        observation = connection.execute(
            "SELECT COUNT(*) AS count FROM observations WHERE source_key = ?",
            (canonical,),
        ).fetchone()["count"]
        jobs = connection.execute(
            """
            SELECT COUNT(*) AS count FROM source_sync_jobs
            WHERE source_type = 'rss_atom' AND source_key = ?
            """,
            (canonical,),
        ).fetchone()["count"]
    assert selected == 0
    assert observation == 1
    assert jobs == 0

    with _public_dns():
        again = client.post("/v1/me/sources", headers=auth_headers, json={"kind": "rss_atom", "url": url})
    assert again.status_code == 201
    assert again.json()["id"] == subscription_id
    with database.connect() as connection:
        selected = connection.execute(
            """
            SELECT selected FROM source_sync_subscriptions
            WHERE source_type = 'rss_atom' AND source_key = ?
            """,
            (canonical,),
        ).fetchone()["selected"]
        observation = connection.execute(
            "SELECT COUNT(*) AS count FROM observations WHERE source_key = ?",
            (canonical,),
        ).fetchone()["count"]
        jobs = connection.execute(
            """
            SELECT COUNT(*) AS count FROM source_sync_jobs
            WHERE source_type = 'rss_atom' AND source_key = ?
            """,
            (canonical,),
        ).fetchone()["count"]
    assert selected == 1
    assert observation == 1
    assert jobs == 1


def test_remove_keeps_leased_job_until_lease_expires(
    client: TestClient,
    database: Database,
    auth_headers: dict[str, str],
) -> None:
    created = client.post(
        "/v1/me/sources",
        headers=auth_headers,
        json={"kind": "statuspage", "pageId": "abcd1234"},
    )
    assert created.status_code == 201
    worker = WatchSyncWorker(get_settings(), database, lease_seconds=120)
    now = int(time.time())
    claimed = worker.claim_due(now=now)
    assert [(job.source_type, job.source_key) for job in claimed] == [("statuspage", "abcd1234")]

    removed = client.delete(f"/v1/me/sources/{created.json()['id']}", headers=auth_headers)
    assert removed.status_code == 204
    with database.connect() as connection:
        selected = connection.execute(
            """
            SELECT selected FROM source_sync_subscriptions
            WHERE source_type = 'statuspage' AND source_key = 'abcd1234'
            """
        ).fetchone()["selected"]
        jobs = connection.execute(
            """
            SELECT COUNT(*) AS count FROM source_sync_jobs
            WHERE source_type = 'statuspage' AND source_key = 'abcd1234'
            """
        ).fetchone()["count"]
    assert selected == 0
    assert jobs == 1

    worker.refresh_jobs(now=now + 121)
    with database.connect() as connection:
        jobs = connection.execute(
            """
            SELECT COUNT(*) AS count FROM source_sync_jobs
            WHERE source_type = 'statuspage' AND source_key = 'abcd1234'
            """
        ).fetchone()["count"]
    assert jobs == 0


def test_invalid_and_unlisted_urls_are_rejected_before_persist(
    client: TestClient,
    database: Database,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    _enable_feed_hosts(monkeypatch, "official.example")
    http = client.post(
        "/v1/me/sources",
        headers=auth_headers,
        json={"kind": "rss_atom", "url": "http://official.example/feed.xml"},
    )
    assert http.status_code == 422
    unlisted = client.post(
        "/v1/me/sources",
        headers=auth_headers,
        json={"kind": "rss_atom", "url": "https://attacker.example/feed.xml"},
    )
    assert unlisted.status_code == 403
    bad_statuspage = client.post(
        "/v1/me/sources",
        headers=auth_headers,
        json={"kind": "statuspage", "pageId": "nope"},
    )
    assert bad_statuspage.status_code == 422
    html = client.post(
        "/v1/me/sources",
        headers=auth_headers,
        json={"kind": "official_changelog", "url": "https://official.example/notes"},
    )
    assert html.status_code == 422
    assert _count_subscriptions(database) == 0
    assert _count_subscription_users(database) == 0
    assert _count_jobs(database) == 0


def test_missing_source_identity_is_validation_not_generic(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    missing_url = client.post(
        "/v1/me/sources",
        headers=auth_headers,
        json={"kind": "rss_atom"},
    )
    assert missing_url.status_code == 422
    assert missing_url.json()["error"]["code"] == "validation_error"
    assert missing_url.json()["error"]["message"] == "url is required"

    missing_statuspage = client.post(
        "/v1/me/sources",
        headers=auth_headers,
        json={"kind": "statuspage"},
    )
    assert missing_statuspage.status_code == 422
    assert missing_statuspage.json()["error"]["message"] == "pageId or url is required for statuspage"


def test_private_ip_feed_is_rejected_before_persist(
    client: TestClient,
    database: Database,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    _enable_feed_hosts(monkeypatch)
    with patch(
        "app.services.rss.socket.getaddrinfo",
        return_value=[(2, 1, 6, "", ("127.0.0.1", 443))],
    ):
        response = client.post(
            "/v1/me/sources",
            headers=auth_headers,
            json={"kind": "rss_atom", "url": "https://news.example.com/feed.xml"},
        )
    assert response.status_code == 403
    assert _count_subscriptions(database) == 0
    assert _count_jobs(database) == 0


def test_cross_user_isolation_does_not_leak_source_keys(
    client: TestClient,
    database: Database,
    monkeypatch,
) -> None:
    _enable_feed_hosts(monkeypatch)
    alice = _auth_headers(client)
    bob = _auth_headers(client)
    with _public_dns():
        alice_feed = client.post(
            "/v1/me/sources",
            headers=alice,
            json={"kind": "rss_atom", "url": "https://alice.example.com/secret.xml"},
        )
        bob_feed = client.post(
            "/v1/me/sources",
            headers=bob,
            json={"kind": "rss_atom", "url": "https://bob.example.com/other.xml"},
        )
        shared = client.post(
            "/v1/me/sources",
            headers=alice,
            json={"kind": "json_feed", "url": "https://shared.example.com/feed.json"},
        )
        shared_again = client.post(
            "/v1/me/sources",
            headers=bob,
            json={"kind": "json_feed", "url": "https://shared.example.com/feed.json"},
        )
    assert alice_feed.status_code == 201
    assert bob_feed.status_code == 201
    assert shared.status_code == 201
    assert shared_again.status_code == 201
    alice_listed = client.get("/v1/me/sources", headers=alice).json()["items"]
    bob_listed = client.get("/v1/me/sources", headers=bob).json()["items"]
    alice_urls = {item["canonicalUrl"] for item in alice_listed}
    bob_urls = {item["canonicalUrl"] for item in bob_listed}
    assert "https://alice.example.com/secret.xml" in alice_urls
    assert "https://alice.example.com/secret.xml" not in bob_urls
    assert "https://bob.example.com/other.xml" in bob_urls
    assert "https://bob.example.com/other.xml" not in alice_urls
    assert "https://shared.example.com/feed.json" in alice_urls
    assert "https://shared.example.com/feed.json" in bob_urls

    stolen = client.delete(f"/v1/me/sources/{alice_feed.json()['id']}", headers=bob)
    assert stolen.status_code == 404
    assert client.get("/v1/me/sources", headers=alice).status_code == 200
    assert any(
        item["id"] == alice_feed.json()["id"]
        for item in client.get("/v1/me/sources", headers=alice).json()["items"]
    )

    removed_shared = client.delete(f"/v1/me/sources/{shared.json()['id']}", headers=alice)
    assert removed_shared.status_code == 204
    bob_remaining = client.get("/v1/me/sources", headers=bob).json()["items"]
    assert any(item["canonicalUrl"] == "https://shared.example.com/feed.json" for item in bob_remaining)
    with database.connect() as connection:
        selected = connection.execute(
            """
            SELECT selected FROM source_sync_subscriptions
            WHERE source_type = 'json_feed' AND source_key = ?
            """,
            ("https://shared.example.com/feed.json",),
        ).fetchone()["selected"]
    assert selected == 1


def test_registry_duplicate_endpoint_is_used_as_subscription_identity(
    client: TestClient,
    database: Database,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    _enable_feed_hosts(monkeypatch)
    registry = SourceRegistry(database)
    existing = registry.register_endpoint(
        url="https://news.example.com/feed.xml",
        family=SourceKind.RSS_ATOM,
        created_at="2026-08-01T00:00:00Z",
    )
    with _public_dns():
        created = client.post(
            "/v1/me/sources",
            headers=auth_headers,
            json={"kind": "rss_atom", "url": "https://www.news.example.com/feed.xml/"},
        )
    assert created.status_code == 201
    assert created.json()["id"] == existing.endpoint_id
    assert created.json()["canonicalUrl"] == existing.canonical_url


def test_main_app_exposes_me_sources_but_not_preview_router(client: TestClient) -> None:
    schema = app.openapi()
    assert "/v1/me/sources" in schema["paths"]
    assert "/v1/sources" not in schema["paths"]
    assert client.get("/v1/sources/statuspage/demo").status_code == 404


def test_account_deletion_removes_subscription_users_not_observations(
    client: TestClient,
    database: Database,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    _enable_feed_hosts(monkeypatch)
    url = "https://news.example.com/feed.xml"
    with _public_dns():
        created = client.post("/v1/me/sources", headers=auth_headers, json={"kind": "rss_atom", "url": url})
    assert created.status_code == 201
    canonical = created.json()["canonicalUrl"]
    _insert_observation(database, source_type="rss_atom", source_key=canonical)

    deleted = client.delete("/v1/me", headers=auth_headers)
    assert deleted.status_code == 204
    assert _count_subscription_users(database, source_type="rss_atom", source_key=canonical) == 0
    with database.connect() as connection:
        selected = connection.execute(
            """
            SELECT selected FROM source_sync_subscriptions
            WHERE source_type = 'rss_atom' AND source_key = ?
            """,
            (canonical,),
        ).fetchone()["selected"]
        observations = connection.execute(
            "SELECT COUNT(*) AS count FROM observations WHERE source_key = ?",
            (canonical,),
        ).fetchone()["count"]
    assert selected == 0
    assert observations == 1
