from fastapi.testclient import TestClient

from app.database import Database
from app.db.seed import seed_catalog, seed_user_workspace
from app.security import token_hash


def _seed_demo_for_authenticated_user(
    database: Database,
    auth_headers: dict[str, str],
) -> None:
    access_token = auth_headers["Authorization"].removeprefix("Bearer ")
    with database.connect() as connection:
        user = connection.execute(
            "SELECT user_id FROM user_sessions WHERE token_hash = ?",
            (token_hash(access_token),),
        ).fetchone()
        assert user is not None
        seed_catalog(connection)
        seed_user_workspace(connection, user["user_id"])


def test_github_repositories_use_pushed_at_not_name(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    async def fake_list(settings, token):
        del settings, token
        return [
            {
                "id": 1,
                "full_name": "aaa/first-by-name",
                "html_url": "https://github.com/aaa/first-by-name",
                "private": False,
                "updated_at": "2026-01-01T00:00:00Z",
                "pushed_at": "2026-08-20T00:00:00Z",
            },
            {
                "id": 2,
                "full_name": "zzz/last-by-name",
                "html_url": "https://github.com/zzz/last-by-name",
                "private": False,
                "updated_at": "2026-08-01T00:00:00Z",
                "pushed_at": "2026-01-01T00:00:00Z",
            },
        ]

    import app.services.github as github_service

    monkeypatch.setattr(github_service, "list_repositories", fake_list)
    listed = client.get(
        "/v1/me/integrations/github/repositories",
        headers=auth_headers,
        params={"limit": 50},
    )
    assert listed.status_code == 200
    assert [item["fullName"] for item in listed.json()["items"]] == [
        "aaa/first-by-name",
        "zzz/last-by-name",
    ]


def test_github_repositories_are_ordered_by_updated_at_desc(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    listed = client.get(
        "/v1/me/integrations/github/repositories",
        headers=auth_headers,
        params={"limit": 50},
    )
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert [item["fullName"] for item in items] == [
        "niyu/BulletFeed",
        "niyu/example-worker",
        "niyu/bulletfeed-web",
        "niyu/worker-api",
    ]
    timestamps = [item["updatedAt"] for item in items]
    assert timestamps == sorted(timestamps, reverse=True)


def test_github_repository_cursor_advances_without_repeating_page(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    first = client.get(
        "/v1/me/integrations/github/repositories",
        headers=auth_headers,
        params={"limit": 2},
    )
    assert first.status_code == 200
    first_body = first.json()
    assert len(first_body["items"]) == 2
    assert first_body["nextCursor"]
    assert [item["fullName"] for item in first_body["items"]] == [
        "niyu/BulletFeed",
        "niyu/example-worker",
    ]

    second = client.get(
        "/v1/me/integrations/github/repositories",
        headers=auth_headers,
        params={"limit": 2, "cursor": first_body["nextCursor"]},
    )
    assert second.status_code == 200
    second_body = second.json()
    assert len(second_body["items"]) == 2
    assert {item["id"] for item in first_body["items"]}.isdisjoint(
        {item["id"] for item in second_body["items"]}
    )
    assert [item["fullName"] for item in second_body["items"]] == [
        "niyu/bulletfeed-web",
        "niyu/worker-api",
    ]


def test_selected_repository_persists_private_visibility(
    client: TestClient,
    auth_headers: dict[str, str],
    database: Database,
) -> None:
    listed = client.get(
        "/v1/me/integrations/github/repositories",
        headers=auth_headers,
        params={"limit": 50},
    )
    private_repo = next(item for item in listed.json()["items"] if item["private"])
    updated = client.put(
        "/v1/me/integrations/github/repositories",
        headers=auth_headers,
        json={"repositoryIds": [private_repo["id"]]},
    )
    assert updated.status_code == 200
    with database.connect() as connection:
        row = connection.execute(
            "SELECT private FROM github_repo_watches WHERE repository_id = ?",
            (private_repo["id"],),
        ).fetchone()
    assert row["private"] == 1


def test_github_repositories_and_disconnect(client: TestClient, auth_headers: dict[str, str]) -> None:
    listed = client.get("/v1/me/integrations/github/repositories", headers=auth_headers, params={"limit": 2})
    assert listed.status_code == 200
    body = listed.json()
    assert len(body["items"]) == 2
    assert "connected" not in body
    first_id = body["items"][0]["id"]

    updated = client.put(
        "/v1/me/integrations/github/repositories",
        headers=auth_headers,
        json={"repositoryIds": [first_id]},
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["connected"] is True
    assert "addedTopics" in body
    assert "alreadyTrackedTopics" in body

    connection = client.get("/v1/me/integrations/github", headers=auth_headers)
    assert connection.status_code == 200
    assert "repositories" not in connection.json()

    removed = client.delete("/v1/me/integrations/github", headers=auth_headers)
    assert removed.status_code == 204
    assert client.get("/v1/me/integrations/github", headers=auth_headers).json()["connected"] is False


def test_github_repository_delta_save_commits_before_topic_sync(
    client: TestClient,
    auth_headers: dict[str, str],
    database: Database,
    monkeypatch,
) -> None:
    listed = client.get(
        "/v1/me/integrations/github/repositories",
        headers=auth_headers,
        params={"limit": 1},
    )
    repository_id = listed.json()["items"][0]["id"]

    async def get_one(settings, selected_id, token):
        del settings, token
        return next(repo for repo in DEMO_REPOSITORIES if str(repo["id"]) == selected_id)

    from app.db.seed import DEMO_REPOSITORIES
    from app.services import github as github_service

    monkeypatch.setattr(github_service, "get_repository_by_id", get_one)
    updated = client.patch(
        "/v1/me/integrations/github/repositories",
        headers=auth_headers,
        json={"addRepositoryIds": [repository_id], "removeRepositoryIds": []},
    )

    assert updated.status_code == 200, updated.text
    assert updated.json()["topicSyncState"] == "pending"
    assert updated.json()["addedTopics"] == []
    status_response = client.get(
        "/v1/me/integrations/github/topic-sync",
        headers=auth_headers,
    )
    assert status_response.status_code == 200
    assert status_response.json()["state"] == "pending"
    with database.connect() as connection:
        assert connection.execute(
            "SELECT 1 FROM github_repo_watches WHERE repository_id = ? AND selected = 1",
            (repository_id,),
        ).fetchone()


def test_saving_github_repositories_returns_inferred_topics(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    from app.services import repository_topic_inference as inference
    from app.services.inferred_priors import make_inferred_signal

    def _named(full_name: str, *topics: str):
        return [
            signal
            for name in topics
            if (
                signal := make_inferred_signal(
                    repository=full_name,
                    signal_type="language",
                    topic_name=name,
                    observed_at="2026-08-29T00:00:00Z",
                )
            )
            is not None
        ]

    async def fake_infer(settings, full_name, token):
        del settings, token
        return _named(full_name, "Kotlin", "Android", "FastAPI")

    monkeypatch.setattr(inference, "infer_repository_prior_signals", fake_infer)

    listed = client.get(
        "/v1/me/integrations/github/repositories",
        headers=auth_headers,
        params={"limit": 1},
    )
    repo_id = listed.json()["items"][0]["id"]

    updated = client.put(
        "/v1/me/integrations/github/repositories",
        headers=auth_headers,
        json={"repositoryIds": [repo_id]},
    )
    assert updated.status_code == 200
    body = updated.json()
    assert set(body["addedTopics"]) == {"Kotlin", "Android", "FastAPI"}
    assert body["alreadyTrackedTopics"] == []
    assert body["inspectedRepositoryCount"] == 1
    assert body["failedRepositoryCount"] == 0

    topics = client.get("/v1/me/topics", headers=auth_headers)
    assert topics.json()["items"] == []

    client.post("/v1/me/topics", headers=auth_headers, json={"name": "Redis", "type": "technology"})

    async def fake_infer_with_overlap(settings, full_name, token):
        del settings, token
        return _named(full_name, "Kotlin", "Redis", "PostgreSQL")

    monkeypatch.setattr(inference, "infer_repository_prior_signals", fake_infer_with_overlap)
    again = client.put(
        "/v1/me/integrations/github/repositories",
        headers=auth_headers,
        json={"repositoryIds": [repo_id]},
    )
    assert again.status_code == 200
    assert again.json()["addedTopics"] == ["PostgreSQL"]
    assert set(again.json()["alreadyTrackedTopics"]) == {"Kotlin", "Redis"}

    topics = client.get("/v1/me/topics", headers=auth_headers)
    assert {item["name"] for item in topics.json()["items"]} == {"Redis"}


def test_github_authorize_requires_config(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.post("/v1/me/integrations/github/authorize", headers=auth_headers)
    assert response.status_code == 503
    assert "error" in response.json()


def test_new_user_security_and_notification_surfaces_are_empty(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    alerts = client.get("/v1/me/security/alerts", headers=auth_headers)
    notifications = client.get("/v1/me/notifications", headers=auth_headers)

    assert alerts.status_code == 200
    assert alerts.json()["items"] == []
    assert notifications.status_code == 200
    assert notifications.json()["items"] == []


def test_security_alerts_and_notifications(
    client: TestClient,
    auth_headers: dict[str, str],
    database: Database,
) -> None:
    _seed_demo_for_authenticated_user(database, auth_headers)

    alerts = client.get("/v1/me/security/alerts", headers=auth_headers)
    assert alerts.status_code == 200
    assert any(item["id"] == "vuln-next-auth" for item in alerts.json()["items"])

    patched = client.patch(
        "/v1/me/security/alerts/vuln-next-auth",
        headers=auth_headers,
        json={"status": "in_progress"},
    )
    assert patched.status_code == 200
    assert patched.json()["status"] == "in_progress"
    assert client.get("/v1/me/security/alerts/missing", headers=auth_headers).status_code == 404

    unread = client.get("/v1/me/notifications", headers=auth_headers, params={"status": "unread"})
    assert unread.status_code == 200
    assert all(item["read"] is False for item in unread.json()["items"])

    marked = client.patch(
        "/v1/me/notifications/notification-next-auth",
        headers=auth_headers,
        json={"read": True},
    )
    assert marked.json()["read"] is True
    result = client.post("/v1/me/notifications/read-all", headers=auth_headers)
    assert result.json()["updatedCount"] >= 1
