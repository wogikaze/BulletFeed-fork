import pytest
from cryptography.fernet import Fernet

from app import sync_worker
from app.config import Settings
from app.database import Database
from app.security import TokenCipher
from app.sync_worker import WatchSyncWorker


def _database_with_watch(tmp_path):
    database = Database(tmp_path / "sync.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES ('user_1', 0), ('user_2', 0)")
        connection.execute(
            """
            INSERT INTO github_repo_watches (
                user_id, repository_id, full_name, html_url, selected, private
            ) VALUES
                ('user_1', '1', 'acme/widget', 'https://github.com/acme/widget', 1, 0),
                ('user_2', '1', 'acme/widget', 'https://github.com/acme/widget', 1, 0)
            """
        )
    return database


@pytest.mark.asyncio
async def test_worker_syncs_each_source_once_per_repository_and_respects_poll_window(
    tmp_path,
    monkeypatch,
) -> None:
    database = _database_with_watch(tmp_path)
    settings = Settings(database_path=database.path)
    calls: list[tuple[str, str, str, str | None]] = []

    async def fake_release(settings, database, *, owner, repository, retrieved_at, token=None):
        del settings, database, retrieved_at
        calls.append(("github_release", owner, repository, token))

    async def fake_security(settings, database, *, owner, repository, retrieved_at, token=None):
        del settings, database, retrieved_at
        calls.append(("dependency_security", owner, repository, token))

    monkeypatch.setattr(sync_worker, "crawl_github_release_events", fake_release)
    monkeypatch.setattr(sync_worker, "crawl_sbom_security_events", fake_security)
    worker = WatchSyncWorker(settings, database, poll_interval_seconds=300, batch_size=10)

    first = await worker.run_once(now=1_000)
    duplicate = await worker.run_once(now=1_000)
    second_window = await worker.run_once(now=1_300)

    assert (first.attempted, first.succeeded, first.failed) == (2, 2, 0)
    assert duplicate.attempted == 0
    assert (second_window.attempted, second_window.succeeded, second_window.failed) == (2, 2, 0)
    assert calls == [
        ("dependency_security", "acme", "widget", None),
        ("github_release", "acme", "widget", None),
        ("dependency_security", "acme", "widget", None),
        ("github_release", "acme", "widget", None),
    ]

    with database.connect() as connection:
        rows = connection.execute(
            "SELECT * FROM source_sync_jobs ORDER BY source_type"
        ).fetchall()
    assert len(rows) == 2
    assert {row["source_key"] for row in rows} == {"acme/widget"}
    assert {row["next_run_at"] for row in rows} == {1_600}
    assert {row["failure_count"] for row in rows} == {0}


@pytest.mark.asyncio
async def test_run_once_only_leases_the_job_currently_executing(tmp_path, monkeypatch) -> None:
    database = _database_with_watch(tmp_path)
    settings = Settings(database_path=database.path)
    active_lease_counts: list[int] = []

    async def record_lease(settings, database, **kwargs):
        del settings, kwargs
        with database.connect() as connection:
            active_lease_counts.append(
                connection.execute(
                    "SELECT COUNT(*) FROM source_sync_jobs WHERE lease_token IS NOT NULL"
                ).fetchone()[0]
            )

    monkeypatch.setattr(sync_worker, "crawl_github_release_events", record_lease)
    monkeypatch.setattr(sync_worker, "crawl_sbom_security_events", record_lease)
    worker = WatchSyncWorker(settings, database, batch_size=10)

    summary = await worker.run_once(now=1_500)

    assert summary.attempted == 2
    assert active_lease_counts == [1, 1]


@pytest.mark.asyncio
async def test_source_failures_retry_independently_with_exponential_backoff(
    tmp_path,
    monkeypatch,
) -> None:
    database = _database_with_watch(tmp_path)
    settings = Settings(database_path=database.path)
    security_attempts = 0
    release_attempts = 0

    async def fake_release(settings, database, *, owner, repository, retrieved_at, token=None):
        nonlocal release_attempts
        del settings, database, owner, repository, retrieved_at, token
        release_attempts += 1

    async def fake_security(settings, database, *, owner, repository, retrieved_at, token=None):
        nonlocal security_attempts
        del settings, database, owner, repository, retrieved_at, token
        security_attempts += 1
        if security_attempts < 3:
            raise RuntimeError("temporary OSV failure")

    monkeypatch.setattr(sync_worker, "crawl_github_release_events", fake_release)
    monkeypatch.setattr(sync_worker, "crawl_sbom_security_events", fake_security)
    worker = WatchSyncWorker(
        settings,
        database,
        poll_interval_seconds=300,
        retry_base_seconds=30,
        retry_max_seconds=300,
        batch_size=10,
    )

    first = await worker.run_once(now=2_000)
    early = await worker.run_once(now=2_029)
    second_failure = await worker.run_once(now=2_030)
    second_early = await worker.run_once(now=2_089)
    recovered = await worker.run_once(now=2_090)

    assert (first.succeeded, first.failed) == (1, 1)
    assert early.attempted == 0
    assert (second_failure.attempted, second_failure.failed) == (1, 1)
    assert second_early.attempted == 0
    assert (recovered.attempted, recovered.succeeded, recovered.failed) == (1, 1, 0)
    assert release_attempts == 1
    assert security_attempts == 3

    with database.connect() as connection:
        release = connection.execute(
            """
            SELECT * FROM source_sync_jobs
            WHERE source_type = 'github_release' AND source_key = 'acme/widget'
            """
        ).fetchone()
        security = connection.execute(
            """
            SELECT * FROM source_sync_jobs
            WHERE source_type = 'dependency_security' AND source_key = 'acme/widget'
            """
        ).fetchone()
    assert release["next_run_at"] == 2_300
    assert release["last_success_at"] == 2_000
    assert security["failure_count"] == 0
    assert security["next_run_at"] == 2_390
    assert security["last_success_at"] == 2_090
    assert security["last_error"] is None


def test_job_claims_are_leased_across_workers_and_stale_finishes_are_ignored(tmp_path) -> None:
    database = _database_with_watch(tmp_path)
    settings = Settings(database_path=database.path)
    first_worker = WatchSyncWorker(settings, database, lease_seconds=120, batch_size=10)
    second_worker = WatchSyncWorker(settings, database, lease_seconds=120, batch_size=10)

    first_worker.refresh_jobs(now=3_000)
    first_claim = first_worker.claim_due(now=3_000)
    competing_claim = second_worker.claim_due(now=3_000)
    recovered_claim = second_worker.claim_due(now=3_121)

    assert len(first_claim) == 2
    assert competing_claim == []
    assert len(recovered_claim) == 2
    first_by_source = {job.source_type: job for job in first_claim}
    recovered_by_source = {job.source_type: job for job in recovered_claim}
    assert set(recovered_by_source) == {"github_release", "dependency_security"}
    assert recovered_by_source["github_release"].lease_token != first_by_source["github_release"].lease_token

    first_worker._finish_success(first_by_source["github_release"], now=3_122)
    with database.connect() as connection:
        release = connection.execute(
            """
            SELECT * FROM source_sync_jobs
            WHERE source_type = 'github_release' AND source_key = 'acme/widget'
            """
        ).fetchone()
    assert release["next_run_at"] == 3_000
    assert release["lease_token"] == recovered_by_source["github_release"].lease_token

    second_worker._finish_success(recovered_by_source["github_release"], now=3_122)
    with database.connect() as connection:
        release = connection.execute(
            """
            SELECT * FROM source_sync_jobs
            WHERE source_type = 'github_release' AND source_key = 'acme/widget'
            """
        ).fetchone()
    assert release["next_run_at"] == 3_422
    assert release["lease_token"] is None


def test_lease_heartbeat_extension_prevents_reclaim_of_active_job(tmp_path) -> None:
    database = _database_with_watch(tmp_path)
    settings = Settings(database_path=database.path)
    first_worker = WatchSyncWorker(settings, database, lease_seconds=120, batch_size=10)
    second_worker = WatchSyncWorker(settings, database, lease_seconds=120, batch_size=10)

    first_worker.refresh_jobs(now=3_500)
    active = first_worker.claim_due(now=3_500, limit=1)[0]
    assert first_worker._extend_lease(active, now=3_619) is True
    claimed = second_worker.claim_due(now=3_621, limit=1)

    assert claimed
    assert claimed[0].source_type != active.source_type


@pytest.mark.asyncio
async def test_revoked_github_access_deselects_watch_before_source_crawl(tmp_path, monkeypatch) -> None:
    database = Database(tmp_path / "private-sync.db")
    database.initialize()
    key = Fernet.generate_key().decode()
    cipher = TokenCipher(key)
    settings = Settings(database_path=database.path, token_encryption_key=key)
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO users (id, created_at, github_user_id) VALUES ('user_1', 0, 123)"
        )
        connection.execute(
            """
            INSERT INTO github_connections (
                github_user_id, login, github_token_encrypted, token_expires_at, updated_at
            ) VALUES (123, 'user', ?, NULL, 1)
            """,
            (cipher.encrypt("token"),),
        )
        connection.execute(
            """
            INSERT INTO github_repo_watches (
                user_id, repository_id, full_name, html_url, selected, private
            ) VALUES ('user_1', '1', 'acme/private', 'https://github.com/acme/private', 1, 1)
            """
        )

    async def inaccessible(settings, owner, repository, token):
        del settings, owner, repository, token
        return None

    async def should_not_crawl(*args, **kwargs):
        del args, kwargs
        raise AssertionError("revoked repository must not be crawled")

    monkeypatch.setattr(sync_worker.github, "repository_accessible", inaccessible)
    monkeypatch.setattr(sync_worker, "crawl_github_release_events", should_not_crawl)
    monkeypatch.setattr(sync_worker, "crawl_sbom_security_events", should_not_crawl)

    summary = await WatchSyncWorker(settings, database, batch_size=10).run_once(now=4_500)

    assert summary.failed == 0
    with database.connect() as connection:
        watch = connection.execute(
            "SELECT selected FROM github_repo_watches WHERE user_id = 'user_1'"
        ).fetchone()
    assert watch["selected"] == 0


def test_refresh_removes_jobs_after_last_watch_is_removed(tmp_path) -> None:
    database = _database_with_watch(tmp_path)
    settings = Settings(database_path=database.path)
    worker = WatchSyncWorker(settings, database)

    worker.refresh_jobs(now=4_000)
    with database.connect() as connection:
        count = connection.execute("SELECT COUNT(*) AS count FROM source_sync_jobs").fetchone()["count"]
        assert count == 2
        connection.execute("DELETE FROM github_repo_watches")

    worker.refresh_jobs(now=4_001)
    with database.connect() as connection:
        count = connection.execute("SELECT COUNT(*) AS count FROM source_sync_jobs").fetchone()["count"]
        assert count == 0


def _subscribe_source(database: Database, source_type: str, source_key: str, *, selected: int = 1) -> None:
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO source_sync_subscriptions (source_type, source_key, selected)
            VALUES (?, ?, ?)
            ON CONFLICT(source_type, source_key) DO UPDATE SET selected = excluded.selected
            """,
            (source_type, source_key, selected),
        )


def test_non_repo_source_key_can_be_inserted_claimed_succeeded_and_retried(tmp_path) -> None:
    database = Database(tmp_path / "statuspage-sync.db")
    database.initialize()
    settings = Settings(database_path=database.path)
    worker = WatchSyncWorker(
        settings,
        database,
        poll_interval_seconds=300,
        retry_base_seconds=30,
        retry_max_seconds=300,
        lease_seconds=120,
        batch_size=10,
    )
    _subscribe_source(database, "statuspage", "pg_acme")

    worker.refresh_jobs(now=5_000)
    claimed = worker.claim_due(now=5_000)
    assert [(job.source_type, job.source_key) for job in claimed] == [("statuspage", "pg_acme")]

    worker._finish_failure(claimed[0], RuntimeError("temporary fetch failure"), now=5_000)
    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT next_run_at, failure_count, last_error
            FROM source_sync_jobs
            WHERE source_type = 'statuspage' AND source_key = 'pg_acme'
            """
        ).fetchone()
    assert row["failure_count"] == 1
    assert row["next_run_at"] == 5_030
    assert row["last_error"] is not None

    retried = worker.claim_due(now=5_030)
    assert len(retried) == 1
    worker._finish_success(retried[0], now=5_030)
    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT next_run_at, failure_count, last_success_at, last_error, lease_token
            FROM source_sync_jobs
            WHERE source_type = 'statuspage' AND source_key = 'pg_acme'
            """
        ).fetchone()
    assert row["failure_count"] == 0
    assert row["next_run_at"] == 5_330
    assert row["last_success_at"] == 5_030
    assert row["last_error"] is None
    assert row["lease_token"] is None


def test_refresh_removes_unsubscribed_non_repo_job_after_lease_expires(tmp_path) -> None:
    database = Database(tmp_path / "rss-sync.db")
    database.initialize()
    settings = Settings(database_path=database.path)
    worker = WatchSyncWorker(settings, database, lease_seconds=120)
    _subscribe_source(database, "rss", "https://status.acme.example/feed.xml")

    worker.refresh_jobs(now=6_000)
    leased = worker.claim_due(now=6_000)
    assert len(leased) == 1
    _subscribe_source(database, "rss", "https://status.acme.example/feed.xml", selected=0)

    worker.refresh_jobs(now=6_001)
    with database.connect() as connection:
        count = connection.execute(
            """
            SELECT COUNT(*) AS count FROM source_sync_jobs
            WHERE source_type = 'rss' AND source_key = 'https://status.acme.example/feed.xml'
            """
        ).fetchone()["count"]
    assert count == 1

    worker.refresh_jobs(now=6_121)
    with database.connect() as connection:
        count = connection.execute(
            """
            SELECT COUNT(*) AS count FROM source_sync_jobs
            WHERE source_type = 'rss' AND source_key = 'https://status.acme.example/feed.xml'
            """
        ).fetchone()["count"]
    assert count == 0


@pytest.mark.asyncio
async def test_non_repo_jobs_do_not_use_github_repository_access(tmp_path, monkeypatch) -> None:
    database = Database(tmp_path / "public-feed-sync.db")
    database.initialize()
    settings = Settings(database_path=database.path)
    _subscribe_source(database, "rss", "https://status.acme.example/feed.xml")

    async def should_not_authorize(*args, **kwargs):
        del args, kwargs
        raise AssertionError("non-repo source keys must not use GitHub repository access")

    async def should_not_crawl(*args, **kwargs):
        del args, kwargs
        raise AssertionError("non-repo source keys must not run GitHub crawls")

    monkeypatch.setattr(sync_worker.github, "repository_accessible", should_not_authorize)
    monkeypatch.setattr(sync_worker, "crawl_github_release_events", should_not_crawl)
    monkeypatch.setattr(sync_worker, "crawl_sbom_security_events", should_not_crawl)

    summary = await WatchSyncWorker(settings, database, batch_size=10).run_once(now=7_000)

    assert (summary.attempted, summary.succeeded, summary.failed) == (1, 1, 0)
