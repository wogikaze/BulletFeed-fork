import sqlite3
import time

from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import Database
from app.db.release_lifecycle import (
    install_release_lifecycle_guards,
    record_worker_heartbeat,
)
from app.db.seed import seed_catalog, seed_user_workspace


def _seed_workspace(database: Database) -> str:
    with database.connect() as connection:
        user = connection.execute("SELECT id FROM users ORDER BY created_at DESC LIMIT 1").fetchone()
        assert user is not None
        seed_catalog(connection)
        seed_user_workspace(connection, user["id"])
        return str(user["id"])


def test_feed_delivery_is_not_exposure_or_knownness(
    client: TestClient,
    auth_headers: dict[str, str],
    database: Database,
) -> None:
    user_id = _seed_workspace(database)
    with database.connect() as connection:
        before_known = connection.execute(
            "SELECT COUNT(*) AS count FROM user_claim_exposures WHERE user_id = ?",
            (user_id,),
        ).fetchone()["count"]
        before_exposed = connection.execute(
            "SELECT COUNT(*) AS count FROM exposures WHERE user_id = ?",
            (user_id,),
        ).fetchone()["count"]
    assert before_known == 0
    assert before_exposed == 0

    feed_response = client.get("/v1/feed", headers=auth_headers, params={"limit": 20})
    assert feed_response.status_code == 200
    items = feed_response.json()["items"]
    assert items
    assert items[0]["sources"]

    with database.connect() as connection:
        after_delivery_known = connection.execute(
            "SELECT COUNT(*) AS count FROM user_claim_exposures WHERE user_id = ?",
            (user_id,),
        ).fetchone()["count"]
        after_delivery_exposed = connection.execute(
            "SELECT COUNT(*) AS count FROM exposures WHERE user_id = ?",
            (user_id,),
        ).fetchone()["count"]
    assert after_delivery_known == 0
    assert after_delivery_exposed == 0

    exposed = client.post(
        "/v1/feed/exposures",
        headers=auth_headers,
        json={
            "items": [
                {
                    "deliveryId": items[0]["deliveryId"],
                    "displayedAt": "2026-08-23T00:00:00Z",
                }
            ]
        },
    )
    assert exposed.status_code == 200
    assert exposed.json()["accepted"] == 1

    with database.connect() as connection:
        after_exposure = connection.execute(
            "SELECT COUNT(*) AS count FROM exposures WHERE user_id = ?",
            (user_id,),
        ).fetchone()["count"]
    assert after_exposure == 1
    # Canonical claim knownness is asserted against ledger-projected feed items in
    # test_user_knownness.py. Demo workspace rows may intentionally have no claim map.


def test_refresh_token_rotates_without_changing_user(client: TestClient) -> None:
    created = client.post("/v1/sessions")
    assert created.status_code == 200
    first = created.json()

    rotated = client.post(
        "/v1/sessions/refresh",
        json={"refreshToken": first["refreshToken"]},
    )
    assert rotated.status_code == 200
    second = rotated.json()
    assert second["userId"] == first["userId"]
    assert second["accessToken"] != first["accessToken"]
    assert second["refreshToken"] != first["refreshToken"]

    replay = client.post(
        "/v1/sessions/refresh",
        json={"refreshToken": first["refreshToken"]},
    )
    assert replay.status_code == 401


def test_github_recovery_start_uses_frontend_api_casing(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setenv("BULLETFEED_GITHUB_CLIENT_ID", "client-id")
    monkeypatch.setenv("BULLETFEED_GITHUB_CLIENT_SECRET", "client-secret")
    get_settings.cache_clear()

    response = client.post("/v1/sessions/recover/github")
    assert response.status_code == 200
    body = response.json()
    assert body["flowId"]
    assert body["pollToken"]
    assert body["authorizationUrl"].startswith("https://github.com/login/oauth/authorize?")
    assert body["expiresInSeconds"] > 0
    assert "flow_id" not in body


def test_readiness_requires_fresh_worker_heartbeat(
    client: TestClient,
    database: Database,
) -> None:
    missing = client.get("/health/ready")
    assert missing.status_code == 503

    record_worker_heartbeat(database, detail="test")
    ready = client.get("/health/ready")
    assert ready.status_code == 200
    body = ready.json()
    assert body["sourceSyncWorker"] == "ok"
    assert "sourceIngestion" in body
    assert "source_key" not in body
    serialized = str(body)
    assert "acme/" not in serialized
    assert "owner/" not in serialized


def test_worker_watch_revocation_requires_github_reauthorization(database: Database) -> None:
    now = int(time.time())
    install_release_lifecycle_guards(database, now=now)
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO users (
                id, created_at, github_connected, github_credential_state, github_user_id
            ) VALUES (?, ?, 1, 'connected', ?)
            """,
            ("usr_release_guard", now, 424242),
        )
        connection.execute(
            """
            INSERT INTO profiles (user_id, occupation, interests_json, region, updated_at)
            VALUES (?, '', '[]', '', ?)
            """,
            ("usr_release_guard", now),
        )
        connection.execute(
            """
            INSERT INTO github_repo_watches (
                user_id, repository_id, full_name, html_url, selected, private
            ) VALUES (?, ?, ?, ?, 1, 1)
            """,
            ("usr_release_guard", "repo_1", "owner/private", "https://github.com/owner/private"),
        )
        connection.execute(
            "UPDATE github_repo_watches SET selected = 0 WHERE user_id = ? AND repository_id = ?",
            ("usr_release_guard", "repo_1"),
        )
        state = connection.execute(
            "SELECT github_credential_state FROM users WHERE id = ?",
            ("usr_release_guard",),
        ).fetchone()["github_credential_state"]
    assert state == "reauthorization_required"


def test_event_source_kind_must_have_registered_policy(database: Database) -> None:
    install_release_lifecycle_guards(database)
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO events (
                id, title, summary, current_phase, current_summary,
                current_since, current_confidence, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "event_policy_guard",
                "Policy guard",
                "Policy guard",
                "identified",
                "Policy guard",
                "2026-08-23T00:00:00Z",
                "high",
                "2026-08-23T00:00:00Z",
            ),
        )
        try:
            connection.execute(
                """
                INSERT INTO event_sources (
                    id, event_id, publisher, kind, title, url,
                    published_at, retrieved_at, evidence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "source_unknown_policy",
                    "event_policy_guard",
                    "Unknown",
                    "unregistered_kind",
                    "Unknown source",
                    "https://example.com/source",
                    "2026-08-23T00:00:00Z",
                    "2026-08-23T00:00:00Z",
                    "evidence",
                ),
            )
        except sqlite3.IntegrityError as error:
            assert "registered source policy" in str(error)
        else:
            raise AssertionError("unregistered source kind should be rejected")
