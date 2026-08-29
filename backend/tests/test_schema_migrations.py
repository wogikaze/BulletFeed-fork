import sqlite3
from pathlib import Path

import pytest

from app.database import Database
from app.db.ledger_schema import LEDGER_SCHEMA
from app.db.migrations import KNOWN_REVISIONS, UnknownSchemaRevisionError
from app.db.schema import PUBLIC_API_SCHEMA
from app.db.seed import TOPIC_CATALOG
from app.db.source_registry_schema import SOURCE_REGISTRY_SCHEMA
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
        connection.executescript(SOURCE_REGISTRY_SCHEMA)
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
        assert revisions == list(KNOWN_REVISIONS)
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'user_ranking_features'"
        ).fetchone()
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'user_ranking_resets'"
        ).fetchone()
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
        assert "last_new_observation_at" in job_columns
        assert "repository_full_name" not in job_columns
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'source_sync_subscriptions'"
        ).fetchone()
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'source_sync_subscription_users'"
        ).fetchone()
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'app_sessions'"
        ).fetchone() is None
        knownness_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(user_claim_exposures)")
        }
        assert {"state", "displayed_at", "read_at", "delivery_count"} <= knownness_columns
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'source_publishers'"
        ).fetchone()
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'source_endpoints'"
        ).fetchone()
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'source_endpoint_lineage'"
        ).fetchone()
        feedback_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(feedback)")
        }
        assert {"event_id", "delta_id", "claim_id", "family", "superseded"} <= feedback_columns
        ranking_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(user_ranking_features)")
        }
        assert {
            "follow_count",
            "already_knew_count",
            "learned_now_count",
            "less_like_this_count",
        } <= ranking_columns
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'user_knowledge_signals'"
        ).fetchone()
        evidence_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(user_knowledge_evidence)")
        }
        assert {
            "id",
            "user_id",
            "claim_id",
            "event_id",
            "delta_id",
            "kind",
            "provenance",
            "confidence",
            "source_id",
            "created_at",
        } <= evidence_columns


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
        assert revisions == set(KNOWN_REVISIONS)
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


def test_revision_3_adds_subscription_user_mapping(tmp_path: Path) -> None:
    database = Database(tmp_path / "pre-subscription-users.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute("DELETE FROM schema_migrations WHERE revision_id = '3'")
        connection.execute("DROP TABLE IF EXISTS source_sync_subscription_users")

    database.initialize()

    with database.connect() as connection:
        revisions = {
            row[0] for row in connection.execute("SELECT revision_id FROM schema_migrations")
        }
        assert revisions == set(KNOWN_REVISIONS)
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'source_sync_subscription_users'"
        ).fetchone()


def test_revision_4_adds_last_new_observation_at(tmp_path: Path) -> None:
    database = Database(tmp_path / "pre-source-health.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute("DELETE FROM schema_migrations WHERE revision_id = '4'")
        connection.execute(
            """
            CREATE TABLE source_sync_jobs_pre_health (
                source_type TEXT NOT NULL,
                source_key TEXT NOT NULL,
                next_run_at INTEGER NOT NULL,
                lease_until INTEGER NOT NULL DEFAULT 0,
                lease_token TEXT,
                failure_count INTEGER NOT NULL DEFAULT 0,
                last_attempt_at INTEGER,
                last_success_at INTEGER,
                last_error TEXT,
                PRIMARY KEY(source_type, source_key)
            )
            """
        )
        connection.execute(
            """
            INSERT INTO source_sync_jobs_pre_health (
                source_type, source_key, next_run_at, last_success_at, failure_count
            ) VALUES ('github_release', 'acme/widget', 100, 50, 0)
            """
        )
        connection.execute("DROP TABLE source_sync_jobs")
        connection.execute("ALTER TABLE source_sync_jobs_pre_health RENAME TO source_sync_jobs")

    database.initialize()

    with database.connect() as connection:
        revisions = {
            row[0] for row in connection.execute("SELECT revision_id FROM schema_migrations")
        }
        assert revisions == set(KNOWN_REVISIONS)
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(source_sync_jobs)")}
        assert "last_new_observation_at" in columns
        row = connection.execute(
            """
            SELECT last_success_at, last_new_observation_at, failure_count
            FROM source_sync_jobs
            WHERE source_type = 'github_release' AND source_key = 'acme/widget'
            """
        ).fetchone()
        assert row["last_success_at"] == 50
        assert row["last_new_observation_at"] is None
        assert row["failure_count"] == 0
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'source_sync_subscription_users'"
        ).fetchone()


def test_revision_5_drops_app_sessions(tmp_path: Path) -> None:
    database = Database(tmp_path / "pre-app-sessions-drop.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute("DELETE FROM schema_migrations WHERE revision_id = '5'")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS app_sessions (
                token_hash TEXT PRIMARY KEY,
                github_user_id INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                created_at INTEGER NOT NULL
            );
            INSERT INTO app_sessions (token_hash, github_user_id, expires_at, created_at)
            VALUES ('legacy-hash', 123, 1, 1);
            """
        )
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'app_sessions'"
        ).fetchone()

    database.initialize()

    with database.connect() as connection:
        revisions = {
            row[0] for row in connection.execute("SELECT revision_id FROM schema_migrations")
        }
        assert revisions == set(KNOWN_REVISIONS)
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'app_sessions'"
        ).fetchone() is None


def test_revision_7_adds_knownness_states_and_preserves_displayed_rows(tmp_path: Path) -> None:
    database = Database(tmp_path / "pre-knownness-states.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute("DELETE FROM schema_migrations WHERE revision_id = '7'")
        connection.execute(
            """
            CREATE TABLE user_claim_exposures_legacy (
                user_id TEXT NOT NULL,
                claim_id TEXT NOT NULL,
                delivery_id TEXT NOT NULL,
                delivered_at TEXT NOT NULL,
                PRIMARY KEY(user_id, claim_id)
            )
            """
        )
        connection.execute("DROP TABLE user_claim_exposures")
        connection.execute(
            "ALTER TABLE user_claim_exposures_legacy RENAME TO user_claim_exposures"
        )
        connection.execute("INSERT INTO users (id, created_at) VALUES ('user_a', 0)")
        connection.execute(
            """
            INSERT INTO events (
                id, title, summary, current_phase, current_summary,
                current_since, current_confidence, updated_at
            ) VALUES (
                'event_legacy', 'Legacy', 'Legacy', 'identified', 'Legacy',
                '2026-08-22T00:00:00Z', 'high', '2026-08-22T00:00:00Z'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO deltas (
                id, event_id, type, summary, before_text, after_text, occurred_at, active
            ) VALUES (
                'delta_legacy', 'event_legacy', 'state_update', 'Legacy',
                '', 'Legacy', '2026-08-22T00:00:00Z', 1
            )
            """
        )
        connection.execute(
            """
            INSERT INTO feed_items (
                id, user_id, event_id, delta_id, title,
                importance_level, importance_reason, importance_confidence,
                relation_level, relation_reason, matched_topics_json, matched_repos_json,
                status, dismissed, marked_important, updated_at
            ) VALUES (
                'fi_legacy', 'user_a', 'event_legacy', 'delta_legacy', 'Legacy',
                'high', 'test', 0.9, 'direct', 'test', '[]', '[]',
                'read', 0, 0, '2026-08-22T00:00:00Z'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO deliveries (id, feed_item_id, user_id, created_at)
            VALUES ('dlv_legacy', 'fi_legacy', 'user_a', '2026-08-22T00:01:00Z')
            """
        )
        connection.execute(
            """
            INSERT INTO user_claim_exposures (user_id, claim_id, delivery_id, delivered_at)
            VALUES ('user_a', 'claim_legacy', 'dlv_legacy', '2026-08-22T00:02:00Z')
            """
        )

    database.initialize()

    with database.connect() as connection:
        revisions = {
            row[0] for row in connection.execute("SELECT revision_id FROM schema_migrations")
        }
        assert revisions == set(KNOWN_REVISIONS)
        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(user_claim_exposures)")
        }
        assert {"state", "displayed_at", "read_at", "delivery_count"} <= columns
        row = connection.execute(
            """
            SELECT state, displayed_at, read_at, delivery_count
            FROM user_claim_exposures
            WHERE user_id = 'user_a' AND claim_id = 'claim_legacy'
            """
        ).fetchone()
        assert row["state"] == "read"
        assert row["displayed_at"] == "2026-08-22T00:02:00Z"
        assert row["read_at"] == "2026-08-22T00:02:00Z"
        assert row["delivery_count"] == 1


def test_revision_8_adds_source_registry_tables(tmp_path: Path) -> None:
    database = Database(tmp_path / "pre-source-registry.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute("DELETE FROM schema_migrations WHERE revision_id = '8'")
        connection.execute("DROP TABLE IF EXISTS source_endpoint_lineage")
        connection.execute("DROP TABLE IF EXISTS source_endpoints")
        connection.execute("DROP TABLE IF EXISTS source_publishers")

    database.initialize()

    with database.connect() as connection:
        revisions = {
            row[0] for row in connection.execute("SELECT revision_id FROM schema_migrations")
        }
        assert revisions == set(KNOWN_REVISIONS)
        for table in ("source_publishers", "source_endpoints", "source_endpoint_lineage"):
            assert connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table,),
            ).fetchone()
        endpoint_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(source_endpoints)")
        }
        assert {"endpoint_id", "publisher_id", "family", "canonical_url", "previous_endpoint_id"} <= (
            endpoint_columns
        )


def test_revision_9_adds_typed_feedback_tables_and_preserves_rows(tmp_path: Path) -> None:
    database = Database(tmp_path / "pre-typed-feedback.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute("DELETE FROM schema_migrations WHERE revision_id = '9'")
        connection.execute("DROP TABLE IF EXISTS user_knowledge_signals")
        connection.execute("INSERT INTO users (id, created_at) VALUES ('user_a', 0)")
        connection.execute(
            """
            INSERT INTO events (
                id, title, summary, current_phase, current_summary,
                current_since, current_confidence, updated_at
            ) VALUES (
                'event_fb', 'Legacy', 'Legacy', 'identified', 'Legacy',
                '2026-08-22T00:00:00Z', 'high', '2026-08-22T00:00:00Z'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO deltas (
                id, event_id, type, summary, before_text, after_text, occurred_at, active
            ) VALUES (
                'delta_fb', 'event_fb', 'state_update', 'Legacy',
                '', 'Legacy', '2026-08-22T00:00:00Z', 1
            )
            """
        )
        connection.execute(
            """
            INSERT INTO feed_items (
                id, user_id, event_id, delta_id, title,
                importance_level, importance_reason, importance_confidence,
                relation_level, relation_reason, matched_topics_json, matched_repos_json,
                status, dismissed, marked_important, updated_at
            ) VALUES (
                'fi_fb', 'user_a', 'event_fb', 'delta_fb', 'Legacy',
                'high', 'test', 0.9, 'direct', 'test', '[]', '[]',
                'unread', 0, 0, '2026-08-22T00:00:00Z'
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE feedback_legacy (
                id TEXT PRIMARY KEY,
                feed_item_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                type TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO feedback_legacy (id, feed_item_id, user_id, type, created_at)
            VALUES ('fb_legacy', 'fi_fb', 'user_a', 'important', 10)
            """
        )
        connection.execute("DROP TABLE feedback")
        connection.execute("ALTER TABLE feedback_legacy RENAME TO feedback")
        connection.execute(
            """
            CREATE TABLE user_ranking_features_legacy (
                user_id TEXT NOT NULL,
                feature_kind TEXT NOT NULL,
                feature_value TEXT NOT NULL,
                important_count INTEGER NOT NULL,
                not_relevant_count INTEGER NOT NULL,
                PRIMARY KEY (user_id, feature_kind, feature_value)
            )
            """
        )
        connection.execute(
            """
            INSERT INTO user_ranking_features_legacy (
                user_id, feature_kind, feature_value, important_count, not_relevant_count
            ) VALUES ('user_a', 'source_type', 'rss_atom', 2, 1)
            """
        )
        connection.execute("DROP TABLE user_ranking_features")
        connection.execute(
            "ALTER TABLE user_ranking_features_legacy RENAME TO user_ranking_features"
        )

    database.initialize()

    with database.connect() as connection:
        revisions = {
            row[0] for row in connection.execute("SELECT revision_id FROM schema_migrations")
        }
        assert revisions == set(KNOWN_REVISIONS)
        feedback_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(feedback)")
        }
        assert {"event_id", "delta_id", "claim_id", "family", "superseded"} <= feedback_columns
        row = connection.execute(
            "SELECT type, superseded FROM feedback WHERE id = 'fb_legacy'"
        ).fetchone()
        assert row["type"] == "important"
        assert row["superseded"] == 0
        ranking = connection.execute(
            """
            SELECT important_count, not_relevant_count, follow_count,
                   already_knew_count, learned_now_count, less_like_this_count
            FROM user_ranking_features
            WHERE user_id = 'user_a'
            """
        ).fetchone()
        assert tuple(ranking) == (2, 1, 0, 0, 0, 0)
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'user_knowledge_signals'"
        ).fetchone()


def test_revision_10_adds_knowledge_evidence_and_preserves_ledger(tmp_path: Path) -> None:
    database = Database(tmp_path / "pre-knowledge-evidence.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute("DELETE FROM schema_migrations WHERE revision_id = '10'")
        connection.execute("DROP TABLE IF EXISTS user_knowledge_evidence")
        connection.execute("INSERT INTO users (id, created_at) VALUES ('user_a', 0)")
        connection.execute(
            """
            INSERT INTO observations (
                id, source_type, source_key, source_observation_id,
                payload_hash, payload_json, original_url, retrieved_at
            ) VALUES (
                'obs_ke', 'statuspage', 'abcd1234', 'inc_ke',
                'hash', '{}', 'https://example.test', '2026-08-22T00:00:00Z'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO ledger_events (
                id, source_type, source_key, source_event_id, title, created_at
            ) VALUES (
                'event_ke', 'statuspage', 'abcd1234', 'inc_ke', 'Legacy',
                '2026-08-22T00:00:00Z'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO state_claims (
                id, event_id, observation_id, slot, value_text, detail_text,
                valid_at, observed_at
            ) VALUES (
                'claim_ke', 'event_ke', 'obs_ke', 'status', 'investigating', 'Legacy',
                '2026-08-22T00:00:00Z', '2026-08-22T00:00:00Z'
            )
            """
        )

    database.initialize()

    with database.connect() as connection:
        revisions = {
            row[0] for row in connection.execute("SELECT revision_id FROM schema_migrations")
        }
        assert revisions == {"1", "2", "3", "4", "5", "6", "7", "9", "10"}
        assert "8" not in revisions
        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(user_knowledge_evidence)")
        }
        assert {
            "id",
            "user_id",
            "claim_id",
            "event_id",
            "delta_id",
            "kind",
            "provenance",
            "confidence",
            "source_id",
            "created_at",
        } <= columns
        claim = connection.execute(
            "SELECT value_text FROM state_claims WHERE id = 'claim_ke'"
        ).fetchone()
        assert claim["value_text"] == "investigating"
        assert connection.execute(
            "SELECT COUNT(*) FROM user_knowledge_evidence"
        ).fetchone()[0] == 0
