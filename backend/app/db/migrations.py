from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable

from app.db.event_identity_schema import EVENT_IDENTITY_SCHEMA
from app.db.knowledge_evidence_schema import KNOWLEDGE_EVIDENCE_SCHEMA
from app.db.knowledge_identity_schema import KNOWLEDGE_IDENTITY_SCHEMA
from app.db.ledger_schema import LEDGER_SCHEMA
from app.db.schema import PUBLIC_API_SCHEMA
from app.db.session_telemetry_schema import SESSION_TELEMETRY_SCHEMA
from app.db.source_discovery_schema import SOURCE_DISCOVERY_SCHEMA
from app.db.source_registry_schema import SOURCE_REGISTRY_SCHEMA
from app.db.state_ledger_schema import STATE_LEDGER_SCHEMA
from app.db.sync_schema import SYNC_SCHEMA

KNOWN_REVISIONS = (
    "1",
    "2",
    "3",
    "4",
    "5",
    "6",
    "7",
    "8",
    "9",
    "10",
    "11",
    "12",
    "13",
    "14",
    "15",
    "16",
    "17",
)

OAUTH_SCHEMA = """
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


class UnknownSchemaRevisionError(RuntimeError):
    """Raised when the database records a revision this code does not know."""


def apply_schema_migrations(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            revision_id TEXT PRIMARY KEY,
            applied_at INTEGER NOT NULL
        )
        """
    )
    applied = {row[0] for row in connection.execute("SELECT revision_id FROM schema_migrations")}
    unknown = sorted(applied - set(KNOWN_REVISIONS))
    if unknown:
        raise UnknownSchemaRevisionError("Database has unknown schema revision(s): " + ", ".join(unknown))
    for revision_id in KNOWN_REVISIONS:
        if revision_id in applied:
            continue
        _REVISION_APPLIERS[revision_id](connection)
        connection.execute(
            "INSERT INTO schema_migrations (revision_id, applied_at) VALUES (?, ?)",
            (revision_id, int(time.time())),
        )


def _add_column_if_missing(connection: sqlite3.Connection, table: str, definition: str) -> None:
    column_name = definition.split()[0]
    existing = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
    if column_name not in existing:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")


def _apply_revision_1(connection: sqlite3.Connection) -> None:
    connection.executescript(PUBLIC_API_SCHEMA)
    connection.executescript(LEDGER_SCHEMA)
    connection.executescript(STATE_LEDGER_SCHEMA)
    connection.executescript(SYNC_SCHEMA)
    connection.executescript(OAUTH_SCHEMA)
    connection.executescript(EVENT_IDENTITY_SCHEMA)
    for table, definition in (
        ("users", "github_user_id INTEGER"),
        ("users", "github_login TEXT"),
        ("users", "onboarding_state TEXT NOT NULL DEFAULT 'profile'"),
        ("users", "github_credential_state TEXT NOT NULL DEFAULT 'disconnected'"),
        ("oauth_flows", "user_id TEXT"),
        ("oauth_flows", "refresh_token_encrypted TEXT"),
        ("state_claims", "source_updated_at TEXT NOT NULL DEFAULT ''"),
        ("state_claims", "revision_hint TEXT NOT NULL DEFAULT ''"),
        ("github_repo_watches", "private INTEGER NOT NULL DEFAULT 1"),
        ("feed_items", "personalization_rank INTEGER NOT NULL DEFAULT 0"),
        ("deltas", "active INTEGER NOT NULL DEFAULT 1"),
        ("claim_evidence", "dependence_key TEXT NOT NULL DEFAULT ''"),
        ("claim_relations", "decision_reason TEXT NOT NULL DEFAULT ''"),
        ("claim_relations", "decision_confidence TEXT NOT NULL DEFAULT 'high'"),
        ("claim_relations", "decision_version TEXT NOT NULL DEFAULT 'legacy'"),
        ("claim_relations", "decision_abstained INTEGER NOT NULL DEFAULT 0"),
        ("event_identity_aliases", "decision_version TEXT NOT NULL DEFAULT 'manual-v1'"),
        ("event_identity_repairs", "metadata_json TEXT NOT NULL DEFAULT '{}'"),
    ):
        _add_column_if_missing(connection, table, definition)
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_users_github_identity
        ON users(github_user_id)
        WHERE github_user_id IS NOT NULL
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_deltas_event_active ON deltas(event_id, active, occurred_at, id)"
    )


def _apply_revision_2(connection: sqlite3.Connection) -> None:
    job_columns = {row[1] for row in connection.execute("PRAGMA table_info(source_sync_jobs)")}
    if "repository_full_name" in job_columns and "source_key" not in job_columns:
        connection.execute(
            """
            CREATE TABLE source_sync_jobs_v2 (
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
            INSERT INTO source_sync_jobs_v2 (
                source_type, source_key, next_run_at, lease_until, lease_token,
                failure_count, last_attempt_at, last_success_at, last_error
            )
            SELECT
                source_type, repository_full_name, next_run_at, lease_until, lease_token,
                failure_count, last_attempt_at, last_success_at, last_error
            FROM source_sync_jobs
            """
        )
        connection.execute("DROP TABLE source_sync_jobs")
        connection.execute("ALTER TABLE source_sync_jobs_v2 RENAME TO source_sync_jobs")
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_source_sync_jobs_due
            ON source_sync_jobs(next_run_at, lease_until)
            """
        )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS source_sync_subscriptions (
            source_type TEXT NOT NULL,
            source_key TEXT NOT NULL,
            selected INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY(source_type, source_key)
        )
        """
    )


def _apply_revision_3(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS source_sync_subscription_users (
            source_type TEXT NOT NULL,
            source_key TEXT NOT NULL,
            user_id TEXT NOT NULL,
            PRIMARY KEY(source_type, source_key, user_id)
        )
        """
    )


def _apply_revision_4(connection: sqlite3.Connection) -> None:
    _add_column_if_missing(connection, "source_sync_jobs", "last_new_observation_at INTEGER")


def _apply_revision_5(connection: sqlite3.Connection) -> None:
    connection.execute("DROP TABLE IF EXISTS app_sessions")


def _apply_revision_6(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS user_ranking_resets (
            user_id TEXT PRIMARY KEY,
            reset_at INTEGER NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS user_ranking_features (
            user_id TEXT NOT NULL,
            feature_kind TEXT NOT NULL,
            feature_value TEXT NOT NULL,
            important_count INTEGER NOT NULL,
            not_relevant_count INTEGER NOT NULL,
            PRIMARY KEY (user_id, feature_kind, feature_value),
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )


def _apply_revision_7(connection: sqlite3.Connection) -> None:
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "user_claim_exposures" not in tables:
        return
    _add_column_if_missing(connection, "user_claim_exposures", "state TEXT NOT NULL DEFAULT 'displayed'")
    _add_column_if_missing(connection, "user_claim_exposures", "displayed_at TEXT")
    _add_column_if_missing(connection, "user_claim_exposures", "read_at TEXT")
    _add_column_if_missing(connection, "user_claim_exposures", "delivery_count INTEGER NOT NULL DEFAULT 1")
    connection.execute(
        """
        UPDATE user_claim_exposures
        SET displayed_at = COALESCE(displayed_at, delivered_at)
        WHERE displayed_at IS NULL
        """
    )
    connection.execute(
        """
        UPDATE user_claim_exposures
        SET state = 'read', read_at = COALESCE(read_at, delivered_at)
        WHERE state = 'displayed'
          AND EXISTS (
              SELECT 1
              FROM deliveries d
              JOIN feed_items f ON f.id = d.feed_item_id
              WHERE d.id = user_claim_exposures.delivery_id
                AND f.user_id = user_claim_exposures.user_id
                AND f.status = 'read'
          )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_user_claim_exposures_state
        ON user_claim_exposures(user_id, state, claim_id)
        """
    )


def _apply_revision_8(connection: sqlite3.Connection) -> None:
    connection.executescript(SOURCE_REGISTRY_SCHEMA)


def _apply_revision_9(connection: sqlite3.Connection) -> None:
    """Typed feedback linkage, knowledge signals, and expanded ranking tallies.

    Revision 8 is reserved for the source registry (#58).
    """
    for definition in (
        "event_id TEXT",
        "delta_id TEXT",
        "claim_id TEXT",
        "family TEXT",
        "superseded INTEGER NOT NULL DEFAULT 0",
    ):
        _add_column_if_missing(connection, "feedback", definition)
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_feedback_latest
        ON feedback(user_id, feed_item_id, family, superseded, created_at, id)
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS user_knowledge_signals (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            feed_item_id TEXT,
            event_id TEXT,
            delta_id TEXT,
            claim_id TEXT,
            signal TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            superseded INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_user_knowledge_signals_latest
        ON user_knowledge_signals(user_id, event_id, delta_id, claim_id, superseded)
        """
    )
    for definition in (
        "follow_count INTEGER NOT NULL DEFAULT 0",
        "already_knew_count INTEGER NOT NULL DEFAULT 0",
        "learned_now_count INTEGER NOT NULL DEFAULT 0",
        "less_like_this_count INTEGER NOT NULL DEFAULT 0",
    ):
        _add_column_if_missing(connection, "user_ranking_features", definition)


def _apply_revision_10(connection: sqlite3.Connection) -> None:
    """Append-only personal knowledge evidence. Does not touch the factual ledger.

    Revision 8 is reserved for the source registry (#58).
    Revision 9 is typed feedback (#45).
    """
    connection.executescript(KNOWLEDGE_EVIDENCE_SCHEMA)


def _apply_revision_11(connection: sqlite3.Connection) -> None:
    """Audit columns for meaningful viewport display (Known-03).

    Existing exposure rows stay displayed. New clients send dwell_ms and
    visible_ratio; missing metrics remain compatible as displayed.
    """
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "exposures" not in tables:
        return
    _add_column_if_missing(connection, "exposures", "dwell_ms INTEGER")
    _add_column_if_missing(connection, "exposures", "visible_ratio REAL")
    _add_column_if_missing(connection, "exposures", "policy_version TEXT")
    _add_column_if_missing(connection, "exposures", "detail_opened INTEGER NOT NULL DEFAULT 0")


def _apply_revision_12(connection: sqlite3.Connection) -> None:
    """GitHub-inferred interest signals. Does not replace explicit user interests.

    Revision 8 is the source registry (#58). Revisions 9-10 are typed feedback
    and knowledge evidence. Revision 11 is viewport exposure columns.
    """
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS github_inferred_signals (
            user_id TEXT NOT NULL,
            repository TEXT NOT NULL,
            signal_type TEXT NOT NULL,
            topic_name TEXT NOT NULL,
            weight REAL NOT NULL,
            inference_version TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            PRIMARY KEY (user_id, repository, signal_type, topic_name),
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_github_inferred_signals_user
        ON github_inferred_signals(user_id, repository)
        """
    )


def _apply_revision_13(connection: sqlite3.Connection) -> None:
    """Semantic knowledge identity maps. Does not touch the factual ledger.

    Revision 8 is the source registry (#58). Revision 12 is inferred priors.
    """
    connection.executescript(KNOWLEDGE_IDENTITY_SCHEMA)


def _apply_revision_14(connection: sqlite3.Connection) -> None:
    """Per-user source-discovery approve/ignore decisions.

    Discovery is not evidence and does not create subscriptions.
    """
    connection.executescript(SOURCE_DISCOVERY_SCHEMA)


def _apply_revision_15(connection: sqlite3.Connection) -> None:
    """Per-user offline preference weights. Ranking overlay only.

    Does not write Event, Claim, Delta, or Observation rows.
    """
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS user_preference_models (
            user_id TEXT PRIMARY KEY,
            policy_version TEXT NOT NULL,
            schema_version TEXT NOT NULL,
            evidence_count INTEGER NOT NULL,
            fingerprint TEXT NOT NULL,
            trained_at INTEGER NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS user_preference_weights (
            user_id TEXT NOT NULL,
            feature_kind TEXT NOT NULL,
            feature_value TEXT NOT NULL,
            weight REAL NOT NULL,
            evidence_count INTEGER NOT NULL,
            positive_mass REAL NOT NULL,
            negative_mass REAL NOT NULL,
            policy_version TEXT NOT NULL,
            trained_at INTEGER NOT NULL,
            PRIMARY KEY (user_id, feature_kind, feature_value),
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )


def _apply_revision_16(connection: sqlite3.Connection) -> None:
    """Feed-session outcome telemetry. Separate from Event/Claim/Delta."""
    connection.executescript(SESSION_TELEMETRY_SCHEMA)


def _apply_revision_17(connection: sqlite3.Connection) -> None:
    """Persist Relation semantic score for production ranking.

    Level remains the discrete axis. The continuous score is a versioned
    feature so GET /feed and Gold candidates share the same contract.
    Existing rows keep 0.0 / empty version until the next projection.
    """
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "feed_items" not in tables:
        return
    _add_column_if_missing(connection, "feed_items", "relation_score REAL NOT NULL DEFAULT 0.0")
    _add_column_if_missing(
        connection, "feed_items", "relation_feature_version TEXT NOT NULL DEFAULT ''"
    )


_REVISION_APPLIERS: dict[str, Callable[[sqlite3.Connection], None]] = {
    "1": _apply_revision_1,
    "2": _apply_revision_2,
    "3": _apply_revision_3,
    "4": _apply_revision_4,
    "5": _apply_revision_5,
    "6": _apply_revision_6,
    "7": _apply_revision_7,
    "8": _apply_revision_8,
    "9": _apply_revision_9,
    "10": _apply_revision_10,
    "11": _apply_revision_11,
    "12": _apply_revision_12,
    "13": _apply_revision_13,
    "14": _apply_revision_14,
    "15": _apply_revision_15,
    "16": _apply_revision_16,
    "17": _apply_revision_17,
}
