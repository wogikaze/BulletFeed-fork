import time

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.database import Database
from app.db.release_lifecycle import record_worker_heartbeat
from app.services.http import require_json


def _insert_watch(database: Database, *, user_id: str, full_name: str) -> None:
    with database.connect() as connection:
        connection.execute(
            "INSERT OR IGNORE INTO users (id, created_at) VALUES (?, 0)",
            (user_id,),
        )
        connection.execute(
            """
            INSERT INTO github_repo_watches (
                user_id, repository_id, full_name, html_url, selected, private
            ) VALUES (?, ?, ?, ?, 1, 0)
            """,
            (user_id, full_name, full_name, f"https://github.com/{full_name}"),
        )


def _insert_job(
    database: Database,
    *,
    source_key: str,
    last_success_at: int | None,
    failure_count: int,
    last_error: str | None,
    now: int,
) -> None:
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO source_sync_jobs (
                source_type, source_key, next_run_at, failure_count,
                last_attempt_at, last_success_at, last_new_observation_at, last_error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "github_release",
                source_key,
                now + 300,
                failure_count,
                now,
                last_success_at,
                last_success_at,
                last_error,
            ),
        )


@pytest.mark.asyncio
async def test_integrated_stale_heartbeat_source_outage_and_rate_limit(
    client: TestClient,
    database: Database,
) -> None:
    now = int(time.time())
    _insert_watch(database, user_id="user_ops", full_name="acme/outage")
    _insert_watch(database, user_id="user_ops", full_name="acme/ratelimit")
    _insert_job(
        database,
        source_key="acme/outage",
        last_success_at=1,
        failure_count=0,
        last_error=None,
        now=now,
    )
    _insert_job(
        database,
        source_key="acme/ratelimit",
        last_success_at=now,
        failure_count=3,
        last_error="HTTPException: GitHub API rate limit exceeded",
        now=now,
    )

    record_worker_heartbeat(database, now=1, detail="stale")
    blocked = client.get("/health/ready")
    assert blocked.status_code == 503
    assert "stale" in blocked.text.lower()

    record_worker_heartbeat(database, detail="fresh")
    ready = client.get("/health/ready")
    assert ready.status_code == 200
    ingestion = ready.json()["sourceIngestion"]
    assert ready.json()["sourceSyncWorker"] == "ok"
    assert ingestion["status"] == "failing"
    assert ingestion["stale"] == 1
    assert ingestion["failing"] == 1
    assert "acme/" not in str(ready.json())

    sources = client.get("/health/sources")
    assert sources.json()["workerHeartbeat"] == "ok"
    assert sources.json()["sourceIngestion"]["status"] == "failing"

    with pytest.raises(HTTPException) as exc_info:
        await require_json(
            httpx.Response(
                403,
                headers={"x-ratelimit-remaining": "0"},
                json={"message": "API rate limit exceeded"},
            ),
            "GitHub API",
            reauthorization_on_auth_failure=True,
        )
    assert exc_info.value.status_code == 429
    assert "rate limit" in str(exc_info.value.detail).lower()
