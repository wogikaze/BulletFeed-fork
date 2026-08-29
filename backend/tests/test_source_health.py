from fastapi.testclient import TestClient

from app.database import Database
from app.db.release_lifecycle import record_worker_heartbeat
from app.db.source_health import list_source_health, summarize_source_health


def _insert_job(
    database: Database,
    *,
    source_type: str,
    source_key: str,
    last_attempt_at: int | None,
    last_success_at: int | None,
    last_new_observation_at: int | None,
    failure_count: int,
    next_run_at: int,
) -> None:
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO source_sync_jobs (
                source_type, source_key, next_run_at, failure_count,
                last_attempt_at, last_success_at, last_new_observation_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_type,
                source_key,
                next_run_at,
                failure_count,
                last_attempt_at,
                last_success_at,
                last_new_observation_at,
            ),
        )


def _insert_watch(
    database: Database,
    *,
    user_id: str,
    full_name: str,
    private: int,
) -> None:
    with database.connect() as connection:
        connection.execute(
            "INSERT OR IGNORE INTO users (id, created_at) VALUES (?, 0)",
            (user_id,),
        )
        connection.execute(
            """
            INSERT INTO github_repo_watches (
                user_id, repository_id, full_name, html_url, selected, private
            ) VALUES (?, ?, ?, ?, 1, ?)
            """,
            (user_id, full_name, full_name, f"https://github.com/{full_name}", private),
        )


def test_list_source_health_keeps_operational_state_off_the_ledger(database: Database) -> None:
    _insert_watch(database, user_id="user_public", full_name="acme/widget", private=0)
    _insert_job(
        database,
        source_type="github_release",
        source_key="acme/widget",
        last_attempt_at=1_000,
        last_success_at=1_000,
        last_new_observation_at=None,
        failure_count=0,
        next_run_at=1_300,
    )

    records = list_source_health(database)
    assert len(records) == 1
    assert records[0].last_new_observation_at is None
    assert records[0].last_success_at == 1_000
    assert records[0].visibility == "public"

    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM state_claims").fetchone()[0] == 0


def test_heartbeat_ok_is_distinct_from_stale_source(database: Database) -> None:
    _insert_watch(database, user_id="user_public", full_name="acme/widget", private=0)
    _insert_job(
        database,
        source_type="github_release",
        source_key="acme/widget",
        last_attempt_at=100,
        last_success_at=100,
        last_new_observation_at=50,
        failure_count=0,
        next_run_at=400,
    )
    now = 10_000
    record_worker_heartbeat(database, now=now, detail="loop")

    summary = summarize_source_health(database, now=now, stale_after_seconds=600)
    assert summary.worker_heartbeat == "ok"
    assert summary.source_freshness == "stale"
    assert summary.stale == 1
    assert summary.fresh == 0
    assert summary.failing == 0


def test_failing_source_preserves_prior_success_in_health_record(database: Database) -> None:
    _insert_watch(database, user_id="user_public", full_name="acme/widget", private=0)
    _insert_job(
        database,
        source_type="dependency_security",
        source_key="acme/widget",
        last_attempt_at=2_000,
        last_success_at=1_000,
        last_new_observation_at=1_000,
        failure_count=3,
        next_run_at=2_240,
    )

    record = list_source_health(database)[0]
    assert record.failure_count == 3
    assert record.last_success_at == 1_000
    assert record.last_new_observation_at == 1_000
    assert record.is_failing()
    assert record.is_stale(now=1_500, stale_after_seconds=600) is False
    assert record.is_stale(now=1_700, stale_after_seconds=600) is True

    summary = summarize_source_health(database, now=1_700, stale_after_seconds=600)
    assert summary.source_freshness == "failing"
    assert summary.failing == 1
    assert summary.stale == 1


def test_private_source_health_is_fail_closed_and_not_listed(
    client: TestClient,
    database: Database,
) -> None:
    _insert_watch(database, user_id="owner", full_name="acme/secret", private=1)
    _insert_job(
        database,
        source_type="github_release",
        source_key="acme/secret",
        last_attempt_at=100,
        last_success_at=100,
        last_new_observation_at=None,
        failure_count=2,
        next_run_at=400,
    )
    record_worker_heartbeat(database, detail="loop")

    records = list_source_health(database)
    assert records[0].visibility == "private"

    summary = summarize_source_health(database, now=10_000, stale_after_seconds=600)
    assert summary.private_or_unknown == 1
    assert summary.stale == 1
    assert summary.failing == 1
    public = summary.as_public_dict()
    assert "acme/secret" not in str(public)
    assert public["privateOrUnknown"] == 1

    ready = client.get("/health/ready")
    assert ready.status_code == 200
    ready_body = ready.json()
    assert ready_body["sourceSyncWorker"] == "ok"
    assert ready_body["sourceIngestion"]["status"] == "failing"
    assert ready_body["sourceIngestion"]["stale"] == 1
    assert "acme/secret" not in ready.text
    assert "source_key" not in ready.text

    sources = client.get("/health/sources")
    assert sources.status_code == 200
    sources_body = sources.json()
    assert sources_body["workerHeartbeat"] == "ok"
    assert sources_body["sourceIngestion"]["privateOrUnknown"] == 1
    assert set(sources_body["pipeline"]) == {
        "fetch",
        "observation",
        "revision",
        "projection",
        "syncFailure",
    }
    assert "acme/secret" not in sources.text
    assert "last_error" not in sources.text
    assert "source_key" not in sources.text


def test_unknown_subscription_is_not_treated_as_public(database: Database) -> None:
    with database.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES ('user_feed', 0)")
        connection.execute(
            """
            INSERT INTO source_sync_subscription_users (source_type, source_key, user_id)
            VALUES ('rss_atom', 'https://status.acme.example/feed.xml', 'user_feed')
            """
        )
    _insert_job(
        database,
        source_type="rss_atom",
        source_key="https://status.acme.example/feed.xml",
        last_attempt_at=1_000,
        last_success_at=1_000,
        last_new_observation_at=None,
        failure_count=0,
        next_run_at=1_300,
    )

    record = list_source_health(database)[0]
    assert record.visibility == "unknown"
    summary = summarize_source_health(database, now=1_000, stale_after_seconds=600)
    assert summary.private_or_unknown == 1
    public = str(summary.as_public_dict())
    assert "status.acme.example" not in public
    assert "user_feed" not in public


def test_statuspage_identity_is_fail_closed(database: Database) -> None:
    with database.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES ('user_page', 0)")
        connection.execute(
            """
            INSERT INTO source_sync_subscription_users (source_type, source_key, user_id)
            VALUES ('statuspage', 'abcd1234', 'user_page')
            """
        )
    _insert_job(
        database,
        source_type="statuspage",
        source_key="abcd1234",
        last_attempt_at=100,
        last_success_at=100,
        last_new_observation_at=None,
        failure_count=1,
        next_run_at=400,
    )

    record = list_source_health(database)[0]
    assert record.visibility == "unknown"
    public = str(summarize_source_health(database, now=10_000).as_public_dict())
    assert "abcd1234" not in public
    assert "user_page" not in public


def test_readiness_stays_ready_when_only_sources_are_stale(
    client: TestClient,
    database: Database,
) -> None:
    _insert_watch(database, user_id="user_public", full_name="acme/widget", private=0)
    _insert_job(
        database,
        source_type="github_release",
        source_key="acme/widget",
        last_attempt_at=1,
        last_success_at=1,
        last_new_observation_at=1,
        failure_count=0,
        next_run_at=301,
    )
    record_worker_heartbeat(database, detail="fresh")

    ready = client.get("/health/ready")
    assert ready.status_code == 200
    assert ready.json()["sourceSyncWorker"] == "ok"
    assert ready.json()["sourceIngestion"]["status"] == "stale"

    sources = client.get("/health/sources")
    assert sources.json()["workerHeartbeat"] == "ok"
    assert sources.json()["sourceIngestion"]["status"] == "stale"
    assert sources.json()["sourceIngestion"]["stale"] == 1
