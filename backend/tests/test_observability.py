import json
import logging

import pytest

from app import observability, sync_worker
from app.config import Settings
from app.database import Database
from app.observability import record, reset, sanitize, snapshot
from app.services.github_release_pipeline import ingest_github_release_events
from app.sync_worker import WatchSyncWorker

_SECRET_PREFIXES = (
    "ghp_",
    "gho_",
    "ghu_",
    "ghs_",
    "ghr_",
    "github_pat_",
)
_SECRET_VALUES = (
    "ghp_live_secret_value",
    "github_pat_11AAAASECRET",
    "client-secret",
    "Bearer ghp_live_secret_value",
)


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


def _serialized_records() -> str:
    return json.dumps(list(snapshot()), sort_keys=True)


@pytest.fixture(autouse=True)
def _reset_observability() -> None:
    reset()
    yield
    reset()


def test_fixture_ingest_records_observation_and_event_ids(tmp_path, caplog) -> None:
    database = Database(tmp_path / "obs.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES ('user_1', 0)")
        connection.execute(
            """
            INSERT INTO github_repo_watches (
                user_id, repository_id, full_name, html_url, selected
            ) VALUES ('user_1', '42', 'acme/widget', 'https://github.com/acme/widget', 1)
            """
        )

    with caplog.at_level(logging.INFO, logger="bulletfeed.pipeline"):
        result = ingest_github_release_events(
            database,
            owner="acme",
            repository="widget",
            releases=[_release()],
            retrieved_at="2026-08-20T10:02:00Z",
        )

    event_id = result.event_ids[0]
    claim_id = result.claim_ids[0]
    records = snapshot()
    observation_ids = {row["observation_id"] for row in records if "observation_id" in row}
    assert observation_ids
    assert any(
        row.get("event") == "revision"
        and row.get("event_id") == event_id
        and row.get("claim_id") == claim_id
        and row.get("observation_id") in observation_ids
        and row.get("revision_type") == "NEW_FACT"
        for row in records
    )
    assert any(
        row.get("event") == "projection"
        and row.get("layer") == "ledger"
        and row.get("event_id") == event_id
        and row.get("observation_id") in observation_ids
        for row in records
    )
    assert any(
        row.get("event") == "projection"
        and row.get("layer") == "feed"
        and row.get("event_id") == event_id
        for row in records
    )
    logged = " ".join(record_item.getMessage() for record_item in caplog.records)
    assert event_id in logged
    assert next(iter(observation_ids)) in logged


@pytest.mark.asyncio
async def test_captured_logs_omit_common_secret_prefixes_and_values(
    tmp_path, caplog, monkeypatch
) -> None:
    database = Database(tmp_path / "secrets.db")
    database.initialize()
    settings = Settings(
        database_path=database.path,
        github_client_secret="client-secret",
    )
    with database.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES ('user_1', 0)")
        connection.execute(
            """
            INSERT INTO github_repo_watches (
                user_id, repository_id, full_name, html_url, selected, private
            ) VALUES ('user_1', '1', 'acme/widget', 'https://github.com/acme/widget', 1, 0)
            """
        )

    async def explode(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("Authorization: Bearer ghp_live_secret_value client-secret")

    monkeypatch.setattr(sync_worker, "crawl_github_release_events", explode)
    monkeypatch.setattr(sync_worker, "crawl_sbom_security_events", explode)

    record(
        "revision",
        token="ghp_live_secret_value",
        authorization="Bearer ghp_live_secret_value",
        client_secret="client-secret",
        lease_token="lease-should-never-appear",
        source_key="acme/secret",
        github_pat="github_pat_11AAAASECRET",
        note="gho_should_redact",
    )

    with caplog.at_level(logging.INFO, logger="bulletfeed.pipeline"):
        ingest_github_release_events(
            database,
            owner="acme",
            repository="widget",
            releases=[_release()],
            retrieved_at="2026-08-20T10:02:00Z",
        )
        result = await WatchSyncWorker(settings, database, batch_size=10).run_once(now=5_000)

    assert result.failed == 2

    captured = _serialized_records() + " ".join(item.getMessage() for item in caplog.records)
    for secret in _SECRET_VALUES:
        assert secret not in captured
    for prefix in _SECRET_PREFIXES:
        assert prefix not in captured.casefold()
    assert "lease-should-never-appear" not in captured
    assert "client-secret" not in captured
    assert "acme/secret" not in captured
    assert any(row.get("event") == "sync_failure" for row in snapshot())
    assert all("source_key" not in row.keys() for row in snapshot())


def test_sanitize_redacts_blocked_keys_and_prefixes() -> None:
    cleaned = sanitize(
        {
            "token": "ghp_live_secret_value",
            "source_key": "owner/private",
            "safe": "evt_abc",
            "note": "prefix ghs_ABCDEF embedded",
        }
    )
    assert "token" not in cleaned
    assert "source_key" not in cleaned
    assert cleaned["safe"] == "evt_abc"
    assert "ghs_" not in cleaned["note"]
    assert observability.public_counters()["syncFailure"] == 0


@pytest.mark.asyncio
async def test_worker_fetch_and_failure_use_source_key_digest(tmp_path, monkeypatch) -> None:
    database = Database(tmp_path / "digest.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES ('user_1', 0)")
        connection.execute(
            """
            INSERT INTO github_repo_watches (
                user_id, repository_id, full_name, html_url, selected
            ) VALUES ('user_1', '1', 'acme/widget', 'https://github.com/acme/widget', 1)
            """
        )

    async def boom(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("temporary fetch failure")

    monkeypatch.setattr(sync_worker, "crawl_github_release_events", boom)
    monkeypatch.setattr(sync_worker, "crawl_sbom_security_events", boom)
    settings = Settings(database_path=database.path)
    await WatchSyncWorker(settings, database, batch_size=10).run_once(now=1_000)

    fetch_rows = [row for row in snapshot() if row.get("event") == "fetch"]
    assert fetch_rows
    assert all("acme/widget" not in json.dumps(row) for row in snapshot())
    assert all(row.get("source_type") in {"github_release", "dependency_security"} for row in fetch_rows)
    assert all(row.get("source_key_digest") for row in fetch_rows)
