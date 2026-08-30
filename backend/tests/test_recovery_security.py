from __future__ import annotations

import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

from app.database import Database
from app.db.migrations import KNOWN_REVISIONS
from app.services.relation import RELATION_FEATURE_VERSION
from app.services.statuspage_pipeline import StatuspagePipeline
from app.services.web_snapshots import (
    RobotsDecision,
    SnapshotStore,
    WebSnapshot,
    content_hash_for,
    referenced_snapshot_ids,
    snapshot_id_for,
)
from app.stores.feed_store import FeedStore

BACKEND = Path(__file__).resolve().parents[1]
SCRIPTS = BACKEND / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from backup_database import backup_sqlite  # noqa: E402
from record_db_snapshot import database_sha256, record_snapshot  # noqa: E402


def _statuspage_summary() -> dict:
    return {
        "incidents": [
            {
                "id": "inc_lineage",
                "name": "API latency",
                "impact": "major",
                "created_at": "2026-08-22T00:00:00Z",
                "shortlink": "https://stspg.io/inc_lineage",
                "incident_updates": [
                    {
                        "id": "upd_lineage_1",
                        "status": "investigating",
                        "body": "Investigating elevated latency.",
                        "display_at": "2026-08-22T00:00:00Z",
                        "updated_at": "2026-08-22T00:00:00Z",
                    }
                ],
            }
        ]
    }


def _restore_sqlite(backup_path: Path, restored: Path) -> None:
    source = sqlite3.connect(backup_path)
    destination = sqlite3.connect(restored)
    try:
        with destination:
            source.backup(destination)
    finally:
        destination.close()
        source.close()


def _lineage(database: Database) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    with database.connect() as connection:
        observations = tuple(
            row[0]
            for row in connection.execute(
                "SELECT id FROM observations ORDER BY id"
            ).fetchall()
        )
        claims = tuple(
            row[0]
            for row in connection.execute(
                "SELECT id FROM state_claims ORDER BY id"
            ).fetchall()
        )
        evidence = tuple(
            f"{row[0]}|{row[1]}"
            for row in connection.execute(
                """
                SELECT claim_id, observation_id
                FROM claim_evidence
                ORDER BY claim_id, observation_id
                """
            ).fetchall()
        )
    return observations, claims, evidence


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


def test_database_restore_preserves_snapshot_gc_references(tmp_path: Path) -> None:
    live = tmp_path / "snapshot-reference.db"
    database = Database(live)
    database.initialize()
    snapshot_root = tmp_path / "snapshots"
    store = SnapshotStore(snapshot_root)
    body = b"<html>snapshot</html>"
    canonical_url = "https://docs.example.com/changelog"
    snapshot = WebSnapshot(
        snapshot_id=snapshot_id_for(
            canonical_url=canonical_url,
            content_hash=content_hash_for(body),
        ),
        canonical_url=canonical_url,
        retrieved_at="2025-01-01T00:00:00Z",
        content_hash=content_hash_for(body),
        status_code=200,
        headers=(("content-type", "text/html"),),
        body=body,
        etag=None,
        last_modified=None,
        robots=RobotsDecision(
            source_url=canonical_url,
            robots_url=None,
            allowed=True,
            reason="test",
            retrieved_at="2025-01-01T00:00:00Z",
        ),
        final_url=canonical_url,
    )
    store.put(snapshot)
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO observations (
                id, source_type, source_key, source_observation_id,
                payload_hash, payload_json, original_url, retrieved_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "obs_snapshot_restore",
                "generic_web",
                canonical_url,
                "snapshot-restore",
                "payload-hash",
                json.dumps({"snapshot_id": snapshot.snapshot_id}),
                canonical_url,
                "2025-01-01T00:00:00Z",
            ),
        )

    backup_path = backup_sqlite(live, tmp_path / "backups")
    restored = tmp_path / "snapshot-reference-restored.db"
    _restore_sqlite(backup_path, restored)
    restored_db = Database(restored)
    restored_db.initialize()

    assert referenced_snapshot_ids(restored_db) == frozenset({snapshot.snapshot_id})
    result = store.garbage_collect(
        referenced_ids=referenced_snapshot_ids(restored_db),
        retention_days=0,
        now=datetime(2026, 8, 30, tzinfo=UTC),
    )
    assert result.retained_referenced_ids == (snapshot.snapshot_id,)
    assert store.get(snapshot.snapshot_id) is not None


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


def test_backup_restore_reproduces_observation_claim_lineage(tmp_path: Path) -> None:
    live = tmp_path / "lineage.db"
    database = Database(live)
    database.initialize()
    StatuspagePipeline(database).ingest_summary(
        page_id="abcd1234",
        summary=_statuspage_summary(),
        retrieved_at="2026-08-22T00:01:00Z",
    )
    before = _lineage(database)
    assert before[0]
    assert before[1]
    assert before[2]

    backup_path = backup_sqlite(live, tmp_path / "backups")
    restored = tmp_path / "lineage-restored.db"
    _restore_sqlite(backup_path, restored)
    restored_db = Database(restored)
    restored_db.initialize()
    assert _lineage(restored_db) == before
    StatuspagePipeline(restored_db).ingest_summary(
        page_id="abcd1234",
        summary=_statuspage_summary(),
        retrieved_at="2026-08-22T00:02:00Z",
    )
    assert _lineage(restored_db) == before


def test_duplicate_delivery_does_not_rewrite_observation_or_claim_ids(
    tmp_path: Path,
) -> None:
    path = tmp_path / "dup.db"
    database = Database(path)
    database.initialize()
    pipeline = StatuspagePipeline(database)
    pipeline.ingest_summary(
        page_id="abcd1234",
        summary=_statuspage_summary(),
        retrieved_at="2026-08-22T00:01:00Z",
    )
    first = _lineage(database)
    pipeline.ingest_summary(
        page_id="abcd1234",
        summary=_statuspage_summary(),
        retrieved_at="2026-08-22T00:03:00Z",
    )
    assert _lineage(database) == first
