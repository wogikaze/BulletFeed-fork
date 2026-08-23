from fastapi.testclient import TestClient


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
