import pytest
from cryptography.fernet import Fernet

from app import sync_worker
from app.config import Settings
from app.database import Database
from app.db.source_health import list_source_health
from app.security import TokenCipher
from app.services import statuspage_crawler
from app.services.source_subscriptions import add_subscription_user
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


def _subscribe_feed_user(database: Database, source_type: str, source_key: str, user_id: str) -> None:
    with database.connect() as connection:
        connection.execute(
            "INSERT OR IGNORE INTO users (id, created_at) VALUES (?, 0)",
            (user_id,),
        )
        connection.execute(
            """
            INSERT INTO source_sync_subscription_users (source_type, source_key, user_id)
            VALUES (?, ?, ?)
            ON CONFLICT(source_type, source_key, user_id) DO NOTHING
            """,
            (source_type, source_key, user_id),
        )
    _subscribe_source(database, source_type, source_key)


@pytest.mark.asyncio
async def test_run_once_claims_rss_atom_and_json_feed_jobs(tmp_path, monkeypatch) -> None:
    database = Database(tmp_path / "feed-jobs.db")
    database.initialize()
    settings = Settings(database_path=database.path, rss_allowed_hosts="engineering.acme.example")
    rss_url = "https://engineering.acme.example/feed.xml"
    json_url = "https://engineering.acme.example/feed.json"
    _subscribe_feed_user(database, "rss_atom", rss_url, "user_1")
    _subscribe_feed_user(database, "json_feed", json_url, "user_1")
    calls: list[tuple[str, str]] = []

    async def fake_rss(settings, database, *, url, retrieved_at):
        del settings, database, retrieved_at
        calls.append(("rss_atom", url))

    async def fake_json(settings, database, *, url, retrieved_at):
        del settings, database, retrieved_at
        calls.append(("json_feed", url))

    async def should_not_authorize(*args, **kwargs):
        del args, kwargs
        raise AssertionError("feed jobs must not use GitHub repository access")

    async def should_not_crawl_github(*args, **kwargs):
        del args, kwargs
        raise AssertionError("feed jobs must not run GitHub crawls")

    monkeypatch.setattr(sync_worker, "crawl_feed_events", fake_rss)
    monkeypatch.setattr(sync_worker, "crawl_json_feed_events", fake_json)
    monkeypatch.setattr(sync_worker.github, "repository_accessible", should_not_authorize)
    monkeypatch.setattr(sync_worker, "crawl_github_release_events", should_not_crawl_github)
    monkeypatch.setattr(sync_worker, "crawl_sbom_security_events", should_not_crawl_github)

    summary = await WatchSyncWorker(settings, database, batch_size=10).run_once(now=8_000)

    assert (summary.attempted, summary.succeeded, summary.failed) == (2, 2, 0)
    assert calls == [("json_feed", json_url), ("rss_atom", rss_url)]


@pytest.mark.asyncio
async def test_rss_allowlist_miss_fails_job_without_observations(tmp_path) -> None:
    database = Database(tmp_path / "rss-allowlist.db")
    database.initialize()
    settings = Settings(database_path=database.path, rss_allowed_hosts="official.example")
    _subscribe_source(database, "rss_atom", "https://attacker.example/feed.xml")

    summary = await WatchSyncWorker(settings, database, batch_size=10).run_once(now=8_100)

    assert (summary.attempted, summary.succeeded, summary.failed) == (1, 0, 1)
    with database.connect() as connection:
        observations = connection.execute("SELECT COUNT(*) AS count FROM observations").fetchone()["count"]
        job = connection.execute(
            """
            SELECT failure_count, last_error FROM source_sync_jobs
            WHERE source_type = 'rss_atom'
            """
        ).fetchone()
    assert observations == 0
    assert job["failure_count"] == 1
    assert job["last_error"] is not None


@pytest.mark.asyncio
async def test_rss_private_ip_fails_job_without_observations(tmp_path, monkeypatch) -> None:
    database = Database(tmp_path / "rss-private.db")
    database.initialize()
    settings = Settings(database_path=database.path, rss_allowed_hosts="feeds.example.com")
    _subscribe_source(database, "rss_atom", "https://feeds.example.com/feed.xml")

    def fake_getaddrinfo(host, port, *args, **kwargs):
        del host, port, args, kwargs
        return [(2, 1, 6, "", ("127.0.0.1", 443))]

    monkeypatch.setattr("app.services.rss.socket.getaddrinfo", fake_getaddrinfo)

    summary = await WatchSyncWorker(settings, database, batch_size=10).run_once(now=8_200)

    assert (summary.attempted, summary.succeeded, summary.failed) == (1, 0, 1)
    with database.connect() as connection:
        observations = connection.execute("SELECT COUNT(*) AS count FROM observations").fetchone()["count"]
        job = connection.execute(
            "SELECT failure_count FROM source_sync_jobs WHERE source_type = 'rss_atom'"
        ).fetchone()
    assert observations == 0
    assert job["failure_count"] == 1


@pytest.mark.asyncio
async def test_json_feed_allowlist_miss_fails_job_without_observations(tmp_path) -> None:
    database = Database(tmp_path / "json-allowlist.db")
    database.initialize()
    settings = Settings(database_path=database.path, rss_allowed_hosts="official.example")
    _subscribe_source(database, "json_feed", "https://attacker.example/feed.json")

    summary = await WatchSyncWorker(settings, database, batch_size=10).run_once(now=8_300)

    assert (summary.attempted, summary.succeeded, summary.failed) == (1, 0, 1)
    with database.connect() as connection:
        observations = connection.execute("SELECT COUNT(*) AS count FROM observations").fetchone()["count"]
        job = connection.execute(
            "SELECT failure_count FROM source_sync_jobs WHERE source_type = 'json_feed'"
        ).fetchone()
    assert observations == 0
    assert job["failure_count"] == 1


class _FakeNetworkStream:
    def __init__(self, peer: str) -> None:
        self.peer = peer

    def get_extra_info(self, name: str):
        return (self.peer, 443) if name == "server_addr" else None


class _FakeResponse:
    def __init__(self, *, headers: dict[str, str], body: bytes) -> None:
        self.status_code = 200
        self.headers = headers
        self.extensions = {"network_stream": _FakeNetworkStream("93.184.216.34")}
        self._body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def aiter_raw(self):
        yield self._body


class _FakeClient:
    def __init__(self, response: _FakeResponse) -> None:
        self.response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    def stream(self, method: str, url: str, **kwargs):
        del method, url, kwargs
        return self.response


@pytest.mark.asyncio
async def test_run_once_rss_http_is_mockable_and_refetch_keeps_observation_id(
    tmp_path,
    monkeypatch,
) -> None:
    database = Database(tmp_path / "rss-http.db")
    database.initialize()
    feed_url = "https://engineering.acme.example/feed.xml"
    settings = Settings(database_path=database.path, rss_allowed_hosts="engineering.acme.example")
    _subscribe_feed_user(database, "rss_atom", feed_url, "user_1")
    body = b"""<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Acme Engineering</title>
    <item>
      <title>Widget migration guide</title>
      <link>https://engineering.acme.example/widget-migration</link>
      <pubDate>Thu, 20 Aug 2026 10:00:00 +0000</pubDate>
      <description>Initial migration guidance.</description>
    </item>
  </channel>
</rss>
"""
    fake = _FakeClient(
        _FakeResponse(headers={"content-type": "application/rss+xml"}, body=body)
    )
    monkeypatch.setattr("app.services.rss.httpx.AsyncClient", lambda **kwargs: fake)
    monkeypatch.setattr(
        "app.services.rss.socket.getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )

    worker = WatchSyncWorker(settings, database, poll_interval_seconds=300, batch_size=10)
    first = await worker.run_once(now=9_000)
    second = await worker.run_once(now=9_300)

    assert first.failed == 0 and first.succeeded == 1
    assert second.failed == 0 and second.succeeded == 1
    with database.connect() as connection:
        rows = connection.execute("SELECT id FROM observations").fetchall()
        feed_items = connection.execute(
            "SELECT COUNT(*) AS count FROM feed_items WHERE user_id = 'user_1'"
        ).fetchone()["count"]
        exposures = connection.execute("SELECT COUNT(*) AS count FROM user_claim_exposures").fetchone()[
            "count"
        ]
        job = connection.execute(
            """
            SELECT last_success_at, last_new_observation_at, failure_count
            FROM source_sync_jobs
            WHERE source_type = 'rss_atom'
            """
        ).fetchone()
    assert len(rows) == 1
    assert feed_items >= 1
    assert exposures == 0
    assert job["last_success_at"] == 9_300
    assert job["last_new_observation_at"] == 9_000
    assert job["failure_count"] == 0


@pytest.mark.asyncio
async def test_run_once_json_feed_http_is_mockable(tmp_path, monkeypatch) -> None:
    database = Database(tmp_path / "json-http.db")
    database.initialize()
    feed_url = "https://engineering.acme.example/feed.json"
    settings = Settings(database_path=database.path, rss_allowed_hosts="engineering.acme.example")
    _subscribe_feed_user(database, "json_feed", feed_url, "user_1")
    body = (
        b'{"version":"https://jsonfeed.org/version/1.1","title":"Acme",'
        b'"feed_url":"https://engineering.acme.example/feed.json","items":[{'
        b'"id":"widget-migration","url":"https://engineering.acme.example/widget",'
        b'"title":"Widget","summary":"Guidance.","date_published":"2026-08-20T10:00:00Z"}]}'
    )
    fake = _FakeClient(
        _FakeResponse(headers={"content-type": "application/feed+json"}, body=body)
    )
    monkeypatch.setattr("app.services.json_feed.httpx.AsyncClient", lambda **kwargs: fake)
    monkeypatch.setattr(
        "app.services.rss.socket.getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )

    summary = await WatchSyncWorker(settings, database, batch_size=10).run_once(now=9_400)

    assert (summary.attempted, summary.succeeded, summary.failed) == (1, 1, 0)
    with database.connect() as connection:
        rows = connection.execute("SELECT id FROM observations").fetchall()
        feed_items = connection.execute(
            "SELECT COUNT(*) AS count FROM feed_items WHERE user_id = 'user_1'"
        ).fetchone()["count"]
    assert len(rows) == 1
    assert feed_items >= 1


def _statuspage_summary() -> dict:
    return {
        "incidents": [
            {
                "id": "inc_1",
                "name": "API latency",
                "impact": "major",
                "created_at": "2026-08-22T00:00:00Z",
                "shortlink": "https://stspg.io/inc_1",
                "incident_updates": [
                    {
                        "id": "upd_1",
                        "status": "investigating",
                        "body": "Investigating elevated latency.",
                        "created_at": "2026-08-22T00:00:00Z",
                        "updated_at": "2026-08-22T00:00:00Z",
                        "display_at": "2026-08-22T00:00:00Z",
                    },
                    {
                        "id": "upd_2",
                        "status": "identified",
                        "body": "Database saturation identified.",
                        "created_at": "2026-08-22T00:10:00Z",
                        "updated_at": "2026-08-22T00:10:00Z",
                        "display_at": "2026-08-22T00:10:00Z",
                    },
                ],
            }
        ]
    }


def _database_with_statuspage(tmp_path, *, subscribers: tuple[str, ...] = ("user_1",)):
    database = Database(tmp_path / "statuspage-worker.db")
    database.initialize()
    with database.connect() as connection:
        for user_id in subscribers:
            connection.execute(
                "INSERT INTO users (id, created_at) VALUES (?, 0)",
                (user_id,),
            )
    for user_id in subscribers:
        add_subscription_user(
            database,
            source_type="statuspage",
            source_key="abcd1234",
            user_id=user_id,
        )
    return database


@pytest.mark.asyncio
async def test_run_once_executes_due_statuspage_job_with_mocked_http(tmp_path, monkeypatch) -> None:
    database = _database_with_statuspage(tmp_path)
    settings = Settings(database_path=database.path)
    fetched: list[str] = []

    async def fake_summary(settings, page_id):
        del settings
        fetched.append(page_id)
        return _statuspage_summary()

    monkeypatch.setattr(statuspage_crawler.statuspage, "get_summary", fake_summary)
    worker = WatchSyncWorker(settings, database, poll_interval_seconds=300, batch_size=10)

    summary = await worker.run_once(now=10_000)

    assert fetched == ["abcd1234"]
    assert (summary.attempted, summary.succeeded, summary.failed) == (1, 1, 0)
    with database.connect() as connection:
        events = connection.execute("SELECT id, current_phase FROM events").fetchall()
        feed_count = connection.execute(
            "SELECT COUNT(*) AS count FROM feed_items WHERE user_id = 'user_1'"
        ).fetchone()["count"]
        jobs = connection.execute(
            """
            SELECT source_type FROM source_sync_jobs
            WHERE source_type IN ('rss_atom', 'json_feed')
            """
        ).fetchall()
    assert len(events) == 1
    assert events[0]["current_phase"] == "identified"
    assert feed_count >= 1
    assert jobs == []


@pytest.mark.asyncio
async def test_statuspage_refetch_same_summary_does_not_increase_active_deltas(
    tmp_path,
    monkeypatch,
) -> None:
    database = _database_with_statuspage(tmp_path)
    settings = Settings(database_path=database.path)

    async def fake_summary(settings, page_id):
        del settings, page_id
        return _statuspage_summary()

    monkeypatch.setattr(statuspage_crawler.statuspage, "get_summary", fake_summary)
    worker = WatchSyncWorker(settings, database, poll_interval_seconds=300, batch_size=10)

    first = await worker.run_once(now=11_000)
    with database.connect() as connection:
        first_active = connection.execute(
            "SELECT COUNT(*) AS count FROM deltas WHERE active = 1"
        ).fetchone()["count"]
    second = await worker.run_once(now=11_300)

    assert first.succeeded == 1
    assert second.succeeded == 1
    assert first_active > 0
    with database.connect() as connection:
        second_active = connection.execute(
            "SELECT COUNT(*) AS count FROM deltas WHERE active = 1"
        ).fetchone()["count"]
    assert second_active == first_active


@pytest.mark.asyncio
async def test_statuspage_projects_feed_only_for_mapped_subscribers(tmp_path, monkeypatch) -> None:
    database = Database(tmp_path / "statuspage-audience.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO users (id, created_at) VALUES ('user_a', 0), ('user_b', 0)"
        )
    add_subscription_user(
        database,
        source_type="statuspage",
        source_key="abcd1234",
        user_id="user_a",
    )
    settings = Settings(database_path=database.path)

    async def fake_summary(settings, page_id):
        del settings, page_id
        return _statuspage_summary()

    monkeypatch.setattr(statuspage_crawler.statuspage, "get_summary", fake_summary)
    await WatchSyncWorker(settings, database, batch_size=10).run_once(now=12_000)

    with database.connect() as connection:
        by_user = {
            row["user_id"]: row["count"]
            for row in connection.execute(
                "SELECT user_id, COUNT(*) AS count FROM feed_items GROUP BY user_id"
            ).fetchall()
        }
        exposures = connection.execute(
            "SELECT COUNT(*) AS count FROM user_claim_exposures"
        ).fetchone()["count"]
    assert by_user.get("user_a", 0) >= 1
    assert "user_b" not in by_user
    assert exposures == 0


def test_unsubscribed_statuspage_stops_after_lease_expiry(tmp_path) -> None:
    database = _database_with_statuspage(tmp_path)
    settings = Settings(database_path=database.path)
    worker = WatchSyncWorker(settings, database, lease_seconds=120)

    worker.refresh_jobs(now=13_000)
    leased = worker.claim_due(now=13_000)
    assert [(job.source_type, job.source_key) for job in leased] == [("statuspage", "abcd1234")]
    _subscribe_source(database, "statuspage", "abcd1234", selected=0)

    worker.refresh_jobs(now=13_001)
    with database.connect() as connection:
        count = connection.execute(
            """
            SELECT COUNT(*) AS count FROM source_sync_jobs
            WHERE source_type = 'statuspage' AND source_key = 'abcd1234'
            """
        ).fetchone()["count"]
    assert count == 1

    worker.refresh_jobs(now=13_121)
    with database.connect() as connection:
        count = connection.execute(
            """
            SELECT COUNT(*) AS count FROM source_sync_jobs
            WHERE source_type = 'statuspage' AND source_key = 'abcd1234'
            """
        ).fetchone()["count"]
    assert count == 0


def _insert_observation(database: Database, *, source_key: str, observation_id: str) -> None:
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO observations (
                id, source_type, source_key, source_observation_id,
                payload_hash, payload_json, original_url, retrieved_at
            ) VALUES (?, 'github_release', ?, ?, 'hash', '{}', 'https://example.test', '2026-08-29T00:00:00Z')
            """,
            (observation_id, source_key, observation_id),
        )


@pytest.mark.asyncio
async def test_successful_empty_fetch_updates_freshness_not_new_observation(
    tmp_path,
    monkeypatch,
) -> None:
    database = _database_with_watch(tmp_path)
    settings = Settings(database_path=database.path)

    async def empty_crawl(*args, **kwargs):
        del args, kwargs

    monkeypatch.setattr(sync_worker, "crawl_github_release_events", empty_crawl)
    monkeypatch.setattr(sync_worker, "crawl_sbom_security_events", empty_crawl)
    worker = WatchSyncWorker(settings, database, poll_interval_seconds=300, batch_size=10)

    await worker.run_once(now=20_000)

    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT last_attempt_at, last_success_at, last_new_observation_at,
                   failure_count, next_run_at
            FROM source_sync_jobs
            """
        ).fetchall()
    assert len(rows) == 2
    for row in rows:
        assert row["last_attempt_at"] == 20_000
        assert row["last_success_at"] == 20_000
        assert row["last_new_observation_at"] is None
        assert row["failure_count"] == 0
        assert row["next_run_at"] == 20_300


@pytest.mark.asyncio
async def test_successful_fetch_with_new_observation_records_timestamp(
    tmp_path,
    monkeypatch,
) -> None:
    database = _database_with_watch(tmp_path)
    settings = Settings(database_path=database.path)

    async def release_with_observation(settings, database, **kwargs):
        del settings, kwargs
        _insert_observation(
            database, source_key="acme/widget", observation_id="obs_release_new"
        )

    async def empty_security(*args, **kwargs):
        del args, kwargs

    monkeypatch.setattr(sync_worker, "crawl_github_release_events", release_with_observation)
    monkeypatch.setattr(sync_worker, "crawl_sbom_security_events", empty_security)
    worker = WatchSyncWorker(settings, database, poll_interval_seconds=300, batch_size=10)

    await worker.run_once(now=21_000)

    with database.connect() as connection:
        release = connection.execute(
            """
            SELECT last_success_at, last_new_observation_at
            FROM source_sync_jobs
            WHERE source_type = 'github_release'
            """
        ).fetchone()
        security = connection.execute(
            """
            SELECT last_success_at, last_new_observation_at
            FROM source_sync_jobs
            WHERE source_type = 'dependency_security'
            """
        ).fetchone()
    assert release["last_success_at"] == 21_000
    assert release["last_new_observation_at"] == 21_000
    assert security["last_success_at"] == 21_000
    assert security["last_new_observation_at"] is None


@pytest.mark.asyncio
async def test_failed_fetch_preserves_success_and_new_observation_timestamps(
    tmp_path,
    monkeypatch,
) -> None:
    database = _database_with_watch(tmp_path)
    settings = Settings(database_path=database.path)
    fail_security = False

    async def release_ok(*args, **kwargs):
        del args, kwargs

    async def security_maybe_fail(settings, database, **kwargs):
        del settings, kwargs
        if fail_security:
            raise RuntimeError("osv unavailable")
        _insert_observation(
            database, source_key="acme/widget", observation_id="obs_security_new"
        )

    monkeypatch.setattr(sync_worker, "crawl_github_release_events", release_ok)
    monkeypatch.setattr(sync_worker, "crawl_sbom_security_events", security_maybe_fail)
    worker = WatchSyncWorker(
        settings,
        database,
        poll_interval_seconds=300,
        retry_base_seconds=30,
        retry_max_seconds=300,
        batch_size=10,
    )

    await worker.run_once(now=22_000)
    fail_security = True
    second = await worker.run_once(now=22_300)

    assert second.failed == 1
    with database.connect() as connection:
        security = connection.execute(
            """
            SELECT last_attempt_at, last_success_at, last_new_observation_at,
                   failure_count, next_run_at
            FROM source_sync_jobs
            WHERE source_type = 'dependency_security'
            """
        ).fetchone()
        observations = connection.execute("SELECT COUNT(*) AS count FROM observations").fetchone()
    assert security["last_attempt_at"] == 22_300
    assert security["last_success_at"] == 22_000
    assert security["last_new_observation_at"] == 22_000
    assert security["failure_count"] == 1
    assert security["next_run_at"] == 22_330
    assert observations["count"] == 1


@pytest.mark.asyncio
async def test_repeated_failures_use_deterministic_backoff_and_mark_source_stale(
    tmp_path,
    monkeypatch,
) -> None:
    database = _database_with_watch(tmp_path)
    settings = Settings(database_path=database.path)

    async def always_fail(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("source unavailable")

    monkeypatch.setattr(sync_worker, "crawl_github_release_events", always_fail)
    monkeypatch.setattr(sync_worker, "crawl_sbom_security_events", always_fail)
    worker = WatchSyncWorker(
        settings,
        database,
        poll_interval_seconds=300,
        retry_base_seconds=30,
        retry_max_seconds=300,
        batch_size=10,
    )

    first = await worker.run_once(now=23_000)
    second = await worker.run_once(now=23_030)

    assert first.failed == 2
    assert second.failed == 2
    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT failure_count, last_success_at, next_run_at
            FROM source_sync_jobs
            """
        ).fetchall()
    assert {row["failure_count"] for row in rows} == {2}
    assert {row["last_success_at"] for row in rows} == {None}
    assert {row["next_run_at"] for row in rows} == {23_090}

    records = list_source_health(database)
    assert all(record.is_stale(now=24_000, stale_after_seconds=600) for record in records)
    assert all(record.is_failing() for record in records)
