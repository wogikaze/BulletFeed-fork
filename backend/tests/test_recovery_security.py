from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from app.database import Database
from app.db.migrations import KNOWN_REVISIONS
from app.services.relation import RELATION_FEATURE_VERSION
from app.stores.feed_store import FeedStore

BACKEND = Path(__file__).resolve().parents[1]
SCRIPTS = BACKEND / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from backup_database import backup_sqlite  # noqa: E402
from record_db_snapshot import database_sha256, record_snapshot  # noqa: E402


def test_backup_and_snapshot_restore_preserve_identity(tmp_path: Path) -> None:
    live = tmp_path / "live.db"
    database = Database(live)
    database.initialize()
    with database.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES ('user_restore', 1)")

    backup_path = backup_sqlite(live, tmp_path / "backups")
    identity_path = record_snapshot(database_path=live, snapshot_dir=tmp_path / "snapshots")
    restored = tmp_path / "restored.db"
    source = sqlite3.connect(backup_path)
    destination = sqlite3.connect(restored)
    try:
        with destination:
            source.backup(destination)
    finally:
        destination.close()
        source.close()

    assert database_sha256(restored) == database_sha256(backup_path)
    identity = identity_path.read_text(encoding="utf-8")
    assert "schema_revisions" in identity
    restored_db = Database(restored)
    restored_db.initialize()
    with restored_db.connect() as connection:
        row = connection.execute(
            "SELECT id FROM users WHERE id = 'user_restore'"
        ).fetchone()
        assert row is not None
        revisions = {
            item[0] for item in connection.execute("SELECT revision_id FROM schema_migrations")
        }
        assert revisions == set(KNOWN_REVISIONS)


def test_initialize_is_idempotent_across_restart(tmp_path: Path) -> None:
    path = tmp_path / "restart.db"
    first = Database(path)
    first.initialize()
    with first.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES ('user_restart', 1)")
    second = Database(path)
    second.initialize()
    third = Database(path)
    third.initialize()
    with third.connect() as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM users WHERE id = 'user_restart'"
        ).fetchone()[0]
        assert count == 1
        revisions = {
            item[0] for item in connection.execute("SELECT revision_id FROM schema_migrations")
        }
        assert revisions == set(KNOWN_REVISIONS)


def test_feed_list_does_not_cross_tenants(database) -> None:
    with database.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES ('user_a', 0)")
        connection.execute("INSERT INTO users (id, created_at) VALUES ('user_b', 0)")
        connection.execute(
            """
            INSERT INTO events (
                id, title, summary, current_phase, current_summary,
                current_since, current_confidence, updated_at
            ) VALUES (
                'event_a', 'A only', 'summary', 'identified', 'summary',
                '2026-08-22T00:00:00Z', 'high', '2026-08-22T00:00:00Z'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO deltas (
                id, event_id, type, summary, before_text, after_text, occurred_at, active
            ) VALUES (
                'delta_a', 'event_a', 'new_fact', 'summary', '', 'after',
                '2026-08-22T00:00:00Z', 1
            )
            """
        )
        connection.execute(
            """
            INSERT INTO feed_items (
                id, user_id, event_id, delta_id, title, importance_level, importance_reason,
                importance_confidence, relation_level, relation_reason, relation_score,
                relation_feature_version, matched_topics_json, matched_repos_json,
                personalization_rank, status, dismissed, marked_important, updated_at
            ) VALUES (
                'fi_a', 'user_a', 'event_a', 'delta_a', 'A only', 'medium', 'seed',
                'medium', 'adjacent', 'seed', 0.4, ?, '[]', '[]',
                200, 'unread', 0, 0, '2026-08-22T00:00:00Z'
            )
            """,
            (RELATION_FEATURE_VERSION,),
        )

    store = FeedStore(database)
    alice, _ = store.list_feed(
        "user_a", relation=None, item_status=None, cursor=None, limit=10
    )
    bob, _ = store.list_feed(
        "user_b", relation=None, item_status=None, cursor=None, limit=10
    )
    assert [item.id for item in alice] == ["fi_a"]
    assert bob == []
