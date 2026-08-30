"""In-process release smoke used by the #169 script and tests."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.database import Database
from app.db.release_lifecycle import record_worker_heartbeat
from app.dependencies import get_database
from app.evaluation.seeded_load_profile import run_seeded_load_profile
from app.main import app


def run_release_smoke(database_path: Path) -> dict[str, object]:
    if database_path.exists():
        database_path.unlink()
    database = Database(database_path)
    database.initialize()
    record_worker_heartbeat(database, detail="release-smoke")
    app.dependency_overrides[get_database] = lambda: database
    try:
        client = TestClient(app)
        health = client.get("/health")
        ready = client.get("/health/ready")
        session = client.post("/v1/sessions")
        headers = {"Authorization": f"Bearer {session.json()['accessToken']}"}
        profile = run_seeded_load_profile(
            database,
            incident_count=8,
            updates_per_incident=2,
            user_count=1,
        )
        feed = client.get("/v1/feed", headers=headers)
        sources = client.get("/health/sources")
    finally:
        app.dependency_overrides.pop(get_database, None)
    reopened = Database(database_path)
    with reopened.connect() as connection:
        users = connection.execute("SELECT COUNT(*) AS count FROM users").fetchone()["count"]
    return {
        "health": health.status_code,
        "ready": ready.status_code,
        "session": session.status_code,
        "feed": feed.status_code,
        "sources": sources.status_code,
        "usersAfterReopen": int(users),
        "profileVersion": profile.version,
        "projectedItemCount": profile.projected_item_count,
        "bottlenecks": list(profile.bottlenecks),
    }
