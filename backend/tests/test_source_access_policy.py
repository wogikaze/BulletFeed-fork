import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import app.services.statuspage as statuspage_service
from app.database import Database
from app.dependencies import get_database
from app.routers import sources
from app.services.source_access_policy import (
    MAX_ACTIVE_PER_USER,
    MAX_REQUESTS_PER_CLIENT_WINDOW,
    MAX_REQUESTS_PER_WINDOW,
    SourceAccessPolicy,
)


def _source_client(database: Database) -> TestClient:
    source_app = FastAPI()
    source_app.include_router(sources.router)
    source_app.dependency_overrides[get_database] = lambda: database
    return TestClient(source_app)


def test_source_router_is_not_mounted_but_requires_auth_when_test_mounted(
    client: TestClient,
    database: Database,
) -> None:
    assert client.get("/v1/sources/statuspage/demo").status_code == 404
    with _source_client(database) as source_client:
        assert source_client.get("/v1/sources/statuspage/demo").status_code == 401


def test_source_access_policy_caps_concurrency_and_releases(database) -> None:
    policy = SourceAccessPolicy(database)
    leases = [policy.acquire("user_a", now=1_800_000_000) for _ in range(MAX_ACTIVE_PER_USER)]

    with pytest.raises(HTTPException) as exc_info:
        policy.acquire("user_a", now=1_800_000_000)
    assert exc_info.value.status_code == 429

    leases[0].release()
    replacement = policy.acquire("user_a", now=1_800_000_000)
    replacement.release()
    for lease in leases[1:]:
        lease.release()


def test_source_access_policy_caps_rate_per_window(database) -> None:
    policy = SourceAccessPolicy(database)
    now = 1_800_000_000
    for _ in range(MAX_REQUESTS_PER_WINDOW):
        with policy.acquire("user_a", now=now):
            pass

    with pytest.raises(HTTPException) as exc_info:
        policy.acquire("user_a", now=now)
    assert exc_info.value.status_code == 429

    with policy.acquire("user_a", now=now + 60):
        pass


def test_source_client_quota_survives_anonymous_user_rotation(database) -> None:
    policy = SourceAccessPolicy(database)
    now = 1_800_000_000
    for index in range(MAX_REQUESTS_PER_CLIENT_WINDOW):
        with policy.acquire(
            f"user_{index}",
            client_key="same-client",
            now=now,
        ):
            pass

    with pytest.raises(HTTPException) as exc_info:
        policy.acquire(
            "user_after_rotation",
            client_key="same-client",
            now=now,
        )
    assert exc_info.value.status_code == 429


def test_source_cache_round_trip_and_expiry(database) -> None:
    policy = SourceAccessPolicy(database)
    arguments = {"page_id": "demo"}
    policy.put_cached("statuspage_summary", arguments, {"status": "ok"}, now=100)

    assert policy.get_cached("statuspage_summary", arguments, now=159) == {"status": "ok"}
    assert policy.get_cached("statuspage_summary", arguments, now=160) is None


def test_authenticated_source_router_uses_short_ttl_cache_when_test_mounted(
    database: Database,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    calls = 0

    async def fake_summary(settings, page_id):
        nonlocal calls
        del settings
        calls += 1
        return {
            "page": {"name": page_id},
            "status": {"description": "Operational", "indicator": "none"},
            "incidents": [],
            "scheduled_maintenances": [],
        }

    monkeypatch.setattr(statuspage_service, "get_summary", fake_summary)
    with _source_client(database) as source_client:
        first = source_client.get("/v1/sources/statuspage/demo", headers=auth_headers)
        second = source_client.get("/v1/sources/statuspage/demo", headers=auth_headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert calls == 1
