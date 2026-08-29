from fastapi.testclient import TestClient

from app.database import Database
from app.services.feed_projection import FeedProjector
from app.services.rss_pipeline import ingest_feed_events


def test_me_bootstrap_and_profile(client: TestClient, auth_headers: dict[str, str]) -> None:
    me = client.get("/v1/me", headers=auth_headers)
    assert me.status_code == 200
    assert me.json()["onboardingCompleted"] is False
    assert me.json()["onboardingState"] == "profile"
    assert me.json()["topicCount"] == 0

    updated = client.put(
        "/v1/me/profile",
        headers=auth_headers,
        json={"occupation": "Androidエンジニア", "interests": ["モバイル", "AI"], "region": "東京"},
    )
    assert updated.status_code == 200
    assert updated.json()["occupation"] == "Androidエンジニア"
    fetched = client.get("/v1/me/profile", headers=auth_headers)
    assert fetched.json()["interests"] == ["モバイル", "AI"]


def test_topics_crud_search_and_onboarding(client: TestClient) -> None:
    session = client.post("/v1/sessions")
    assert session.status_code == 200
    auth_headers = {"Authorization": f"Bearer {session.json()['accessToken']}"}

    created = client.post(
        "/v1/me/topics",
        headers=auth_headers,
        json={"name": "Kotlin", "type": "technology"},
    )
    assert created.status_code == 201
    topic_id = created.json()["id"]

    patched = client.patch(
        f"/v1/me/topics/{topic_id}",
        headers=auth_headers,
        json={"priority": "high", "order": 1},
    )
    assert patched.status_code == 200
    assert patched.json()["priority"] == "high"

    search = client.get("/v1/topics/search", headers=auth_headers, params={"q": "cloud"})
    assert search.status_code == 200
    assert any(item["name"] == "Cloudflare Workers" for item in search.json()["items"])

    deleted = client.delete(f"/v1/me/topics/{topic_id}", headers=auth_headers)
    assert deleted.status_code == 204
    assert client.delete(f"/v1/me/topics/{topic_id}", headers=auth_headers).status_code == 404

    onboarding = client.put(
        "/v1/me/onboarding",
        headers=auth_headers,
        json={
            "profile": {"occupation": "Webエンジニア", "interests": ["AI", "OSS"], "region": "日本"},
            "topics": ["Kotlin", "GitHub", "Kotlin", "Android", "Flutter", "OpenAI API"],
            "connectGithub": True,
        },
    )
    assert onboarding.status_code == 200
    assert onboarding.json()["completed"] is False
    assert onboarding.json()["state"] == "github_pending"
    assert onboarding.json()["githubAuthorization"]["required"] is True

    me = client.get("/v1/me", headers=auth_headers)
    assert me.json()["onboardingCompleted"] is False
    assert me.json()["onboardingState"] == "github_pending"
    assert me.json()["topicCount"] == 5
    assert me.json()["githubConnected"] is False


def test_adding_topic_reprojects_matching_source_not_unrelated_event(
    client: TestClient,
    database: Database,
    monkeypatch,
) -> None:
    session = client.post("/v1/sessions")
    assert session.status_code == 200
    user_id = session.json()["userId"]
    auth_headers = {"Authorization": f"Bearer {session.json()['accessToken']}"}

    kotlin = ingest_feed_events(
        database,
        preview={
            "title": "Acme Engineering",
            "source_url": "https://engineering.acme.example/feed.xml",
            "items": [
                {
                    "title": "Kotlin 2.3 migration guide",
                    "link": "https://engineering.acme.example/kotlin-2-3",
                    "published": "2026-08-20T15:00:00Z",
                    "updated": "2026-08-20T15:00:00Z",
                    "summary": "Kotlin compiler migration guidance.",
                }
            ],
        },
        retrieved_at="2026-08-20T15:01:00Z",
    ).event_ids[0]
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO events (
                id, title, summary, current_phase, current_summary,
                current_since, current_confidence, updated_at
            ) VALUES (
                'unrelated_noise', 'Horticulture soil notes', 'Garden pH commentary.',
                'identified', 'soil notes', '2026-08-01T00:00:00Z',
                'low', '2026-08-01T00:00:00Z'
            )
            """
        )

    seen: list[str] = []
    original = FeedProjector.project_event_for_user

    def _wrapped(self, *, user_id: str, event_id: str):
        seen.append(event_id)
        return original(self, user_id=user_id, event_id=event_id)

    monkeypatch.setattr(FeedProjector, "project_event_for_user", _wrapped)

    created = client.post(
        "/v1/me/topics",
        headers=auth_headers,
        json={"name": "Kotlin", "type": "technology"},
    )
    assert created.status_code == 201
    assert "unrelated_noise" not in seen
    assert kotlin in seen

    with database.connect() as connection:
        kotlin_count = connection.execute(
            "SELECT COUNT(*) AS count FROM feed_items WHERE user_id = ? AND event_id = ?",
            (user_id, kotlin),
        ).fetchone()["count"]
        unrelated_count = connection.execute(
            "SELECT COUNT(*) AS count FROM feed_items WHERE user_id = ? AND event_id = ?",
            (user_id, "unrelated_noise"),
        ).fetchone()["count"]
        relation = connection.execute(
            "SELECT relation_level FROM feed_items WHERE user_id = ? AND event_id = ?",
            (user_id, kotlin),
        ).fetchone()
    assert kotlin_count >= 1
    assert unrelated_count == 0
    assert relation["relation_level"] == "adjacent"
