import sqlite3
from pathlib import Path

import pytest

from app.database import Database
from app.db.ledger_schema import LEDGER_SCHEMA
from app.db.migrations import UnknownSchemaRevisionError
from app.db.schema import PUBLIC_API_SCHEMA
from app.db.seed import TOPIC_CATALOG
from app.db.state_ledger_schema import STATE_LEDGER_SCHEMA
from app.db.sync_schema import SYNC_SCHEMA


def _schema_signature(connection: sqlite3.Connection) -> dict[str, object]:
    tables = [
        row[0]
        for row in connection.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        )
    ]
    columns = {
        table: tuple(
            (row["name"], row["type"], row["notnull"], row["dflt_value"])
            for row in connection.execute(f"PRAGMA table_info({table})")
        )
        for table in tables
    }
    indexes = {
        table: tuple(
            (row[1], row[2])
            for row in connection.execute(f"PRAGMA index_list({table})")
            if not str(row[1]).startswith("sqlite_")
        )
        for table in tables
    }
    index_columns = {
        name: tuple(
            row[2] for row in connection.execute(f"PRAGMA index_info({name})")
        )
        for table, entries in indexes.items()
        for name, _unique in entries
    }
    return {
        "tables": tuple(tables),
        "columns": columns,
        "indexes": indexes,
        "index_columns": index_columns,
    }


def _install_current_unversioned_schema(database: Database) -> None:
    """Reproduce today's initialize() CREATE/ALTER path without recording revisions."""
    database.path.parent.mkdir(parents=True, exist_ok=True)
    with database.connect() as connection:
        connection.executescript(PUBLIC_API_SCHEMA)
        connection.executescript(LEDGER_SCHEMA)
        connection.executescript(STATE_LEDGER_SCHEMA)
        connection.executescript(SYNC_SCHEMA)
        connection.executemany(
            "INSERT OR IGNORE INTO topic_catalog (id, name, type) VALUES (?, ?, ?)",
            TOPIC_CATALOG,
        )
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS oauth_flows (
                flow_id TEXT PRIMARY KEY,
                state_hash TEXT NOT NULL UNIQUE,
                poll_token_hash TEXT NOT NULL,
                pkce_verifier_encrypted TEXT NOT NULL,
                user_id TEXT,
                status TEXT NOT NULL,
                detail TEXT,
                github_login TEXT,
                app_access_token_encrypted TEXT,
                refresh_token_encrypted TEXT,
                expires_at INTEGER NOT NULL,
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS github_connections (
                github_user_id INTEGER PRIMARY KEY,
                login TEXT NOT NULL,
                avatar_url TEXT,
                github_token_encrypted TEXT NOT NULL,
                token_expires_at INTEGER,
                updated_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS app_sessions (
                token_hash TEXT PRIMARY KEY,
                github_user_id INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                FOREIGN KEY(github_user_id) REFERENCES github_connections(github_user_id)
            );
            """
        )
        for column, table in [
            ("github_user_id INTEGER", "users"),
            ("github_login TEXT", "users"),
            ("onboarding_state TEXT NOT NULL DEFAULT 'profile'", "users"),
            ("github_credential_state TEXT NOT NULL DEFAULT 'disconnected'", "users"),
            ("user_id TEXT", "oauth_flows"),
            ("refresh_token_encrypted TEXT", "oauth_flows"),
            ("source_updated_at TEXT NOT NULL DEFAULT ''", "state_claims"),
            ("revision_hint TEXT NOT NULL DEFAULT ''", "state_claims"),
            ("private INTEGER NOT NULL DEFAULT 1", "github_repo_watches"),
            ("personalization_rank INTEGER NOT NULL DEFAULT 0", "feed_items"),
        ]:
            try:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {column}")
            except sqlite3.OperationalError:
                pass
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_github_identity "
            "ON users(github_user_id) WHERE github_user_id IS NOT NULL"
        )


def test_fresh_init_matches_upgrade_from_current_schema(tmp_path: Path) -> None:
    fresh = Database(tmp_path / "fresh.db")
    fresh.initialize()

    legacy = Database(tmp_path / "legacy.db")
    _install_current_unversioned_schema(legacy)
    with legacy.connect() as connection:
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
        ).fetchone() is None
    legacy.initialize()

    with fresh.connect() as fresh_conn, legacy.connect() as legacy_conn:
        assert _schema_signature(fresh_conn) == _schema_signature(legacy_conn)
        fresh_revisions = {
            row[0]
            for row in fresh_conn.execute("SELECT revision_id FROM schema_migrations")
        }
        legacy_revisions = {
            row[0]
            for row in legacy_conn.execute("SELECT revision_id FROM schema_migrations")
        }
        assert fresh_revisions
        assert fresh_revisions == legacy_revisions


def test_unknown_future_revision_fails_startup(tmp_path: Path) -> None:
    database = Database(tmp_path / "future.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO schema_migrations (revision_id, applied_at) VALUES (?, ?)",
            ("999", 1),
        )

    with pytest.raises(UnknownSchemaRevisionError, match="999"):
        database.initialize()


def test_initialize_records_baseline_revision(tmp_path: Path) -> None:
    database = Database(tmp_path / "baseline.db")
    database.initialize()
    with database.connect() as connection:
        revisions = [
            row[0]
            for row in connection.execute(
                "SELECT revision_id FROM schema_migrations ORDER BY revision_id"
            )
        ]
        assert revisions == ["1", "2"]
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
        ).fetchone()
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(deltas)")
        }
        assert "active" in columns
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'event_identity_aliases'"
        ).fetchone()
        job_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(source_sync_jobs)")
        }
        assert "source_key" in job_columns
        assert "repository_full_name" not in job_columns
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'source_sync_subscriptions'"
        ).fetchone()


LEGACY_SOURCE_SYNC_JOBS = """
CREATE TABLE source_sync_jobs (
    source_type TEXT NOT NULL,
    repository_full_name TEXT NOT NULL,
    next_run_at INTEGER NOT NULL,
    lease_until INTEGER NOT NULL DEFAULT 0,
    lease_token TEXT,
    failure_count INTEGER NOT NULL DEFAULT 0,
    last_attempt_at INTEGER,
    last_success_at INTEGER,
    last_error TEXT,
    PRIMARY KEY(source_type, repository_full_name)
);

CREATE INDEX idx_source_sync_jobs_due
ON source_sync_jobs(next_run_at, lease_until);
"""


def test_revision_2_migrates_existing_repository_jobs_to_source_key(tmp_path: Path) -> None:
    database = Database(tmp_path / "pre-source-key.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute("DELETE FROM schema_migrations WHERE revision_id = '2'")
        connection.execute("DROP TABLE source_sync_jobs")
        connection.execute("DROP TABLE IF EXISTS source_sync_subscriptions")
        connection.executescript(LEGACY_SOURCE_SYNC_JOBS)
        connection.execute(
            """
            INSERT INTO source_sync_jobs (
                source_type, repository_full_name, next_run_at, lease_until, failure_count
            ) VALUES ('github_release', 'acme/widget', 100, 0, 2)
            """
        )

    database.initialize()

    with database.connect() as connection:
        revisions = {
            row[0] for row in connection.execute("SELECT revision_id FROM schema_migrations")
        }
        assert revisions == {"1", "2"}
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(source_sync_jobs)")}
        assert "source_key" in columns
        assert "repository_full_name" not in columns
        row = connection.execute(
            """
            SELECT source_type, source_key, next_run_at, failure_count
            FROM source_sync_jobs
            """
        ).fetchone()
        assert tuple(row) == ("github_release", "acme/widget", 100, 2)
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'source_sync_subscriptions'"
        ).fetchone()
