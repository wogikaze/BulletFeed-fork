import hashlib
import hmac
import json
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import Database
from app.dependencies import get_database
from app.main import app
from app.observability import public_counters, reset, snapshot
from app.services.github_release_pipeline import ingest_github_release_events

WEBHOOK_SECRET = "webhook-test-secret"


def _release() -> dict:
    return {
        "id": 42,
        "tag_name": "v2.0.0",
        "name": "Widget 2.0",
        "html_url": "https://github.com/acme/widget/releases/tag/v2.0.0",
        "created_at": "2026-08-20T10:00:00Z",
        "published_at": "2026-08-20T10:00:00Z",
        "updated_at": "2026-08-20T10:01:00Z",
        "draft": False,
        "prerelease": False,
        "body": "Initial notes.",
    }


def _release_payload() -> dict:
    return {
        "action": "published",
        "release": _release(),
        "repository": {
            "name": "widget",
            "full_name": "acme/widget",
            "owner": {"login": "acme"},
        },
    }


def _push_payload() -> dict:
    return {
        "ref": "refs/heads/main",
        "after": "0000000000000000000000000000000000000001",
        "commits": [{"id": "abc", "message": "touch file", "added": ["README.md"]}],
        "repository": {
            "name": "widget",
            "full_name": "acme/widget",
            "owner": {"login": "acme"},
        },
    }


def _sign(body: bytes, *, secret: str = WEBHOOK_SECRET) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _headers(body: bytes, *, event: str, secret: str = WEBHOOK_SECRET) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "X-GitHub-Event": event,
        "X-GitHub-Delivery": "11111111-1111-1111-1111-111111111111",
        "X-Hub-Signature-256": _sign(body, secret=secret),
    }


@contextmanager
def _webhook_client(
    database: Database,
    monkeypatch,
    *,
    secret: str = WEBHOOK_SECRET,
) -> Iterator[TestClient]:
    monkeypatch.setenv("BULLETFEED_DATABASE_PATH", str(database.path))
    monkeypatch.setenv("BULLETFEED_GITHUB_WEBHOOK_SECRET", secret)
    get_settings.cache_clear()

    def override_database() -> Database:
        return database

    app.dependency_overrides[get_database] = override_database
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def _observation_rows(database) -> list:
    with database.connect() as connection:
        return connection.execute("SELECT * FROM observations ORDER BY id").fetchall()


def _webhook_rows(database) -> list:
    with database.connect() as connection:
        return connection.execute(
            "SELECT * FROM github_webhook_deliveries ORDER BY delivery_id"
        ).fetchall()


def test_missing_signature_is_rejected_without_observations(
    database,
    monkeypatch,
) -> None:
    body = json.dumps(_release_payload()).encode()

    with _webhook_client(database, monkeypatch) as client:
        response = client.post(
        "/v1/webhooks/github",
        content=body,
            headers={"Content-Type": "application/json", "X-GitHub-Event": "release"},
        )

    assert response.status_code == 401
    assert _observation_rows(database) == []


def test_invalid_signature_is_rejected_without_observations(
    database,
    monkeypatch,
) -> None:
    body = json.dumps(_release_payload()).encode()
    reset()
    headers = _headers(body, event="release")
    headers["X-Hub-Signature-256"] = "sha256=" + ("0" * 64)

    with _webhook_client(database, monkeypatch) as client:
        response = client.post("/v1/webhooks/github", content=body, headers=headers)
        health = client.get("/health/sources")

    assert response.status_code == 401
    assert _observation_rows(database) == []
    webhook_records = [row for row in snapshot() if row.get("event") == "webhook"]
    assert webhook_records[-1]["delivery_id"] == "11111111-1111-1111-1111-111111111111"
    assert webhook_records[-1]["signature_valid"] is False
    assert public_counters()["webhookSignatureFailures"] == 1
    assert _webhook_rows(database)[0]["status"] == "rejected_invalid_signature"
    assert health.json()["webhook"]["signatureFailures"] == 1


def test_sha1_signature_is_rejected_without_observations(
    database,
    monkeypatch,
) -> None:
    body = json.dumps(_release_payload()).encode()
    sha1 = hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha1).hexdigest()

    with _webhook_client(database, monkeypatch) as client:
        response = client.post(
            "/v1/webhooks/github",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Event": "release",
                "X-Hub-Signature": f"sha1={sha1}",
            },
        )

    assert response.status_code == 401
    assert _observation_rows(database) == []


def test_verified_release_webhook_ingests_once_on_duplicate_delivery(
    database,
    monkeypatch,
) -> None:
    body = json.dumps(_release_payload(), separators=(",", ":")).encode()
    reset()
    headers = _headers(body, event="release")

    with _webhook_client(database, monkeypatch) as client:
        first = client.post("/v1/webhooks/github", content=body, headers=headers)
        second = client.post("/v1/webhooks/github", content=body, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["deliveryId"] == "11111111-1111-1111-1111-111111111111"
    assert first.json()["eventIds"] == second.json()["eventIds"]
    assert public_counters()["webhookAccepted"] == 2
    observations = _observation_rows(database)
    assert len(observations) == 1
    deliveries = _webhook_rows(database)
    assert len(deliveries) == 1
    assert deliveries[0]["status"] == "ingested"
    assert deliveries[0]["attempt_count"] == 2
    event_id = first.json()["eventIds"][0]
    with database.connect() as connection:
        deltas = connection.execute(
            "SELECT type FROM deltas WHERE event_id = ? AND active = 1 ORDER BY occurred_at, id",
            (event_id,),
        ).fetchall()
    assert [row["type"] for row in deltas] == ["new_fact"]


def test_push_webhook_is_not_stored_as_evidence(
    database,
    monkeypatch,
) -> None:
    body = json.dumps(_push_payload()).encode()

    with _webhook_client(database, monkeypatch) as client:
        response = client.post(
            "/v1/webhooks/github",
            content=body,
            headers=_headers(body, event="push"),
        )

    assert response.status_code == 200
    assert response.json()["ignored"] is True
    assert _webhook_rows(database)[0]["status"] == "ignored"
    assert _observation_rows(database) == []
    with database.connect() as connection:
        evidence = connection.execute("SELECT * FROM claim_evidence").fetchall()
    assert evidence == []


def test_delivery_id_is_bounded_before_observability_and_response(
    database,
    monkeypatch,
) -> None:
    body = json.dumps(_push_payload()).encode()
    headers = _headers(body, event="push")
    headers["X-GitHub-Delivery"] = "d" * 512
    reset()

    with _webhook_client(database, monkeypatch) as client:
        response = client.post("/v1/webhooks/github", content=body, headers=headers)

    assert response.status_code == 200
    assert len(response.json()["deliveryId"]) == 128
    record = next(row for row in snapshot() if row.get("event") == "webhook")
    assert len(record["delivery_id"]) == 128


def test_polling_ingest_still_works_when_webhook_secret_is_missing(
    database,
    monkeypatch,
) -> None:
    body = json.dumps(_release_payload()).encode()
    with _webhook_client(database, monkeypatch, secret="") as client:
        webhook = client.post(
            "/v1/webhooks/github",
            content=body,
            headers=_headers(body, event="release"),
        )
    assert webhook.status_code == 503
    assert _webhook_rows(database)[0]["status"] == "rejected_secret_unconfigured"
    assert _observation_rows(database) == []

    result = ingest_github_release_events(
        database,
        owner="acme",
        repository="widget",
        releases=[_release()],
        retrieved_at="2026-08-20T10:02:00Z",
    )

    assert result.event_ids
    assert len(_observation_rows(database)) == 1


def test_webhook_logs_do_not_include_secret_or_tokens(database, monkeypatch) -> None:
    reset()
    body = json.dumps(_release_payload()).encode()
    with _webhook_client(database, monkeypatch) as client:
        client.post("/v1/webhooks/github", content=body, headers=_headers(body, event="release"))

    logged = json.dumps(list(snapshot()))
    assert WEBHOOK_SECRET not in logged
    assert "ghp_" not in logged
    assert "webhook-test-secret" not in logged
