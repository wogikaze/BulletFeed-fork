from fastapi.testclient import TestClient

from app.database import Database
from app.services.session_abuse_policy import (
    EMPTY_ANONYMOUS_RETENTION_SECONDS,
    MAX_SESSIONS_PER_CLIENT_WINDOW,
    SessionCreationPolicy,
)


def test_create_session_returns_bearer_token_without_demo_feed(client: TestClient) -> None:
    response = client.post("/v1/sessions")
    assert response.status_code == 200
    body = response.json()
    assert body["accessToken"]
    assert body["userId"].startswith("usr_")

    feed = client.get(
        "/v1/feed",
        headers={"Authorization": f"Bearer {body['accessToken']}"},
    )
    assert feed.status_code == 200
    assert feed.json()["items"] == []


def test_anonymous_session_creation_is_rate_limited_per_client(
    client: TestClient,
    database: Database,
) -> None:
    for _ in range(MAX_SESSIONS_PER_CLIENT_WINDOW):
        response = client.post("/v1/sessions")
        assert response.status_code == 200

    rejected = client.post("/v1/sessions")
    assert rejected.status_code == 429

    with database.connect() as connection:
        user_count = connection.execute("SELECT COUNT(*) AS count FROM users").fetchone()["count"]
    assert user_count == MAX_SESSIONS_PER_CLIENT_WINDOW


def test_acceptance_harness_allows_more_anonymous_sessions_than_the_client_window(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setenv("BULLETFEED_ACCEPTANCE_HARNESS", "1")
    for _ in range(MAX_SESSIONS_PER_CLIENT_WINDOW + 5):
        response = client.post("/v1/sessions")
        assert response.status_code == 200


def test_session_policy_prunes_only_empty_stale_anonymous_users(database: Database) -> None:
    now = 1_800_000_000
    created_at = now - EMPTY_ANONYMOUS_RETENTION_SECONDS - 1
    with database.connect() as connection:
        for user_id, occupation in (("usr_empty", ""), ("usr_kept", "developer")):
            connection.execute(
                "INSERT INTO users (id, created_at) VALUES (?, ?)",
                (user_id, created_at),
            )
            connection.execute(
                """
                INSERT INTO profiles (user_id, occupation, interests_json, region, updated_at)
                VALUES (?, ?, '[]', '', ?)
                """,
                (user_id, occupation, created_at),
            )
            connection.execute(
                """
                INSERT INTO user_sessions (token_hash, user_id, expires_at, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (f"access_{user_id}", user_id, now + 3600, created_at),
            )
            connection.execute(
                """
                INSERT INTO user_refresh_tokens (
                    token_hash, user_id, expires_at, created_at, rotated_at, revoked_at
                ) VALUES (?, ?, ?, ?, NULL, NULL)
                """,
                (f"refresh_{user_id}", user_id, now + 3600, created_at),
            )

    SessionCreationPolicy(database).consume("client_a", now=now)

    with database.connect() as connection:
        empty = connection.execute("SELECT 1 FROM users WHERE id = 'usr_empty'").fetchone()
        kept = connection.execute("SELECT 1 FROM users WHERE id = 'usr_kept'").fetchone()
        empty_access = connection.execute(
            "SELECT 1 FROM user_sessions WHERE user_id = 'usr_empty'"
        ).fetchone()
        empty_refresh = connection.execute(
            "SELECT 1 FROM user_refresh_tokens WHERE user_id = 'usr_empty'"
        ).fetchone()
    assert empty is None
    assert empty_access is None
    assert empty_refresh is None
    assert kept is not None


def test_protected_route_requires_bearer(client: TestClient) -> None:
    response = client.get("/v1/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
