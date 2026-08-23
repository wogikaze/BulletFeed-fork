import json
from pathlib import Path

from app.database import Database
from app.services.event_identity_repair import EventIdentityRepairService
from app.services.feed_projection import FeedProjector
from app.services.ledger_projection import LedgerProjector
from app.services.source_ingestion import NormalizedObservation, SourceIngestionPipeline
from app.stores.claim_ledger_store import ClaimLedgerStore


def _database(tmp_path: Path, name: str = "repair.db") -> Database:
    database = Database(tmp_path / name)
    database.initialize()
    return database


def _claim(
    database: Database,
    *,
    source_type: str,
    source_key: str,
    observation_id: str,
    source_event_id: str,
    title: str,
    value: str,
    detail: str,
    at: str,
    canonical_event_key: str | None = None,
):
    observation = SourceIngestionPipeline(database).ingest_many(
        (
            NormalizedObservation(
                source_type=source_type,
                source_key=source_key,
                source_observation_id=observation_id,
                payload={"value": value, "detail": detail},
                original_url=f"https://example.test/{source_type}/{observation_id}",
                published_at=at,
            ),
        ),
        retrieved_at=at,
    )[0]
    return ClaimLedgerStore(database).ingest(
        observation,
        source_event_id=source_event_id,
        canonical_event_key=canonical_event_key,
        title=title,
        slot="state",
        value=value,
        detail=detail,
        valid_at=at,
        evidence_text=detail,
    )


def _snapshot_immutable_ids(database: Database) -> tuple[tuple[str, ...], tuple[str, ...]]:
    with database.connect() as connection:
        observations = tuple(
            row["id"] for row in connection.execute("SELECT id FROM observations ORDER BY id")
        )
        evidence = tuple(
            row["id"] for row in connection.execute("SELECT id FROM claim_evidence ORDER BY id")
        )
    return observations, evidence


def _copy_repair_log(source: Database, target: Database) -> None:
    with source.connect() as connection:
        rows = connection.execute(
            "SELECT * FROM event_identity_repairs ORDER BY created_at, id"
        ).fetchall()
    with target.connect() as connection:
        for row in rows:
            connection.execute(
                """
                INSERT INTO event_identity_repairs (
                    id, operation, source_event_id, target_event_id,
                    claim_ids_json, metadata_json, reason, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"],
                    row["operation"],
                    row["source_event_id"],
                    row["target_event_id"],
                    row["claim_ids_json"],
                    row["metadata_json"],
                    row["reason"],
                    row["created_at"],
                ),
            )


def test_false_split_merge_repairs_projections_knownness_and_replays(tmp_path: Path):
    database = _database(tmp_path)
    first = _claim(
        database,
        source_type="rss_atom",
        source_key="vendor-feed",
        observation_id="retire-announced",
        source_event_id="retire-announced",
        title="Service retirement",
        value="announced",
        detail="Service retirement announced",
        at="2026-08-01T00:00:00Z",
    )
    second = _claim(
        database,
        source_type="json_feed",
        source_key="vendor-json",
        observation_id="retired",
        source_event_id="retired",
        title="Service retirement",
        value="retired",
        detail="Service retirement completed",
        at="2026-08-02T00:00:00Z",
    )
    projector = LedgerProjector(database)
    projector.project_event(first.event_id)
    projector.project_event(second.event_id)
    before_immutable = _snapshot_immutable_ids(database)

    with database.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES ('user-1', 1)")
    feed_ids = FeedProjector(database).project_event_for_user(
        user_id="user-1", event_id=second.event_id
    )
    assert feed_ids
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO deliveries (id, feed_item_id, user_id, created_at) VALUES (?, ?, ?, ?)",
            ("delivery-repair", feed_ids[0], "user-1", "2026-08-03T00:00:00Z"),
        )
        connection.execute(
            """
            INSERT INTO user_claim_exposures (user_id, claim_id, delivery_id, delivered_at)
            VALUES (?, ?, ?, ?)
            """,
            ("user-1", second.claim_id, "delivery-repair", "2026-08-03T00:00:00Z"),
        )

    result = EventIdentityRepairService(database).merge_events(
        source_event_id=second.event_id,
        target_event_id=first.event_id,
        reason="Gold false-split repair",
        created_at="2026-08-04T00:00:00Z",
    )
    assert result.moved_claim_ids == (second.claim_id,)
    assert _snapshot_immutable_ids(database) == before_immutable

    with database.connect() as connection:
        assert connection.execute(
            "SELECT 1 FROM ledger_events WHERE id = ?", (second.event_id,)
        ).fetchone() is None
        assert connection.execute(
            "SELECT COUNT(*) AS count FROM state_claims WHERE event_id = ?",
            (first.event_id,),
        ).fetchone()["count"] == 2
        assert connection.execute(
            "SELECT event_id FROM feed_items WHERE id = ?", (feed_ids[0],)
        ).fetchone()["event_id"] == first.event_id
        known_event = connection.execute(
            """
            SELECT c.event_id
            FROM user_claim_exposures k JOIN state_claims c ON c.id = k.claim_id
            WHERE k.user_id = 'user-1' AND k.claim_id = ?
            """,
            (second.claim_id,),
        ).fetchone()
        assert known_event["event_id"] == first.event_id
        assert connection.execute(
            "SELECT COUNT(*) AS count FROM event_identity_repairs WHERE operation = 'merge'"
        ).fetchone()["count"] == 1
        assert connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM event_source_claim_map m
            LEFT JOIN event_sources s ON s.id = m.source_id
            WHERE s.id IS NULL
            """
        ).fetchone()["count"] == 0

    replay = _database(tmp_path, "merge-replay.db")
    replay_first = _claim(
        replay,
        source_type="rss_atom",
        source_key="vendor-feed",
        observation_id="retire-announced",
        source_event_id="retire-announced",
        title="Service retirement",
        value="announced",
        detail="Service retirement announced",
        at="2026-08-01T00:00:00Z",
    )
    replay_second = _claim(
        replay,
        source_type="json_feed",
        source_key="vendor-json",
        observation_id="retired",
        source_event_id="retired",
        title="Service retirement",
        value="retired",
        detail="Service retirement completed",
        at="2026-08-02T00:00:00Z",
    )
    LedgerProjector(replay).project_event(replay_first.event_id)
    LedgerProjector(replay).project_event(replay_second.event_id)
    _copy_repair_log(database, replay)
    EventIdentityRepairService(replay).replay_repairs()
    with replay.connect() as connection:
        assert connection.execute(
            "SELECT 1 FROM ledger_events WHERE id = ?", (replay_second.event_id,)
        ).fetchone() is None
        assert connection.execute(
            "SELECT event_id FROM state_claims WHERE id = ?", (replay_second.claim_id,)
        ).fetchone()["event_id"] == replay_first.event_id


def test_false_merge_split_repairs_claims_and_fresh_replay_converges(tmp_path: Path):
    database = _database(tmp_path, "split.db")
    first = _claim(
        database,
        source_type="rss_atom",
        source_key="vendor-feed",
        observation_id="service-a",
        source_event_id="service-a",
        canonical_event_key="mistaken-shared-event",
        title="Service change",
        value="enabled",
        detail="Service A enabled",
        at="2026-08-01T00:00:00Z",
    )
    second = _claim(
        database,
        source_type="json_feed",
        source_key="vendor-json",
        observation_id="service-b",
        source_event_id="service-b",
        canonical_event_key="mistaken-shared-event",
        title="Service change",
        value="disabled",
        detail="Service B disabled",
        at="2026-08-02T00:00:00Z",
    )
    assert first.event_id == second.event_id
    LedgerProjector(database).project_event(first.event_id)
    before_immutable = _snapshot_immutable_ids(database)

    result = EventIdentityRepairService(database).split_claims(
        source_event_id=first.event_id,
        claim_ids=(second.claim_id,),
        new_source_event_id="service-b-corrected",
        title="Service B change",
        reason="Gold false-merge repair",
        created_at="2026-08-04T00:00:00Z",
    )
    assert result.target_event_id != first.event_id
    assert _snapshot_immutable_ids(database) == before_immutable
    with database.connect() as connection:
        assert connection.execute(
            "SELECT event_id FROM state_claims WHERE id = ?", (first.claim_id,)
        ).fetchone()["event_id"] == first.event_id
        assert connection.execute(
            "SELECT event_id FROM state_claims WHERE id = ?", (second.claim_id,)
        ).fetchone()["event_id"] == result.target_event_id
        metadata = json.loads(
            connection.execute(
                "SELECT metadata_json FROM event_identity_repairs WHERE operation = 'split'"
            ).fetchone()["metadata_json"]
        )
        assert metadata["new_source_event_id"] == "service-b-corrected"

    replay = _database(tmp_path, "split-replay.db")
    replay_first = _claim(
        replay,
        source_type="rss_atom",
        source_key="vendor-feed",
        observation_id="service-a",
        source_event_id="service-a",
        canonical_event_key="mistaken-shared-event",
        title="Service change",
        value="enabled",
        detail="Service A enabled",
        at="2026-08-01T00:00:00Z",
    )
    replay_second = _claim(
        replay,
        source_type="json_feed",
        source_key="vendor-json",
        observation_id="service-b",
        source_event_id="service-b",
        canonical_event_key="mistaken-shared-event",
        title="Service change",
        value="disabled",
        detail="Service B disabled",
        at="2026-08-02T00:00:00Z",
    )
    LedgerProjector(replay).project_event(replay_first.event_id)
    _copy_repair_log(database, replay)
    EventIdentityRepairService(replay).replay_repairs()
    with replay.connect() as connection:
        assert connection.execute(
            "SELECT event_id FROM state_claims WHERE id = ?", (replay_second.claim_id,)
        ).fetchone()["event_id"] == result.target_event_id


def test_private_merge_keeps_only_intersection_of_restricted_grants(tmp_path: Path):
    database = _database(tmp_path, "private.db")
    target = _claim(
        database,
        source_type="rss_atom",
        source_key="private-a",
        observation_id="target",
        source_event_id="target",
        title="Private event",
        value="one",
        detail="one",
        at="2026-08-01T00:00:00Z",
    )
    source = _claim(
        database,
        source_type="json_feed",
        source_key="private-b",
        observation_id="source",
        source_event_id="source",
        title="Private event",
        value="two",
        detail="two",
        at="2026-08-02T00:00:00Z",
    )
    projector = LedgerProjector(database)
    projector.project_event(target.event_id)
    projector.project_event(source.event_id)
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO users (id, created_at) VALUES ('common', 1), ('target-only', 1), ('source-only', 1)"
        )
        connection.execute(
            "INSERT INTO event_visibility (event_id, restricted) VALUES (?, 1), (?, 1)",
            (target.event_id, source.event_id),
        )
        connection.execute(
            """
            INSERT INTO event_user_access (event_id, user_id, expires_at) VALUES
            (?, 'common', 500), (?, 'target-only', 600),
            (?, 'common', 400), (?, 'source-only', 700)
            """,
            (target.event_id, target.event_id, source.event_id, source.event_id),
        )

    EventIdentityRepairService(database).merge_events(
        source_event_id=source.event_id,
        target_event_id=target.event_id,
        reason="private false split",
        created_at="2026-08-04T00:00:00Z",
    )
    with database.connect() as connection:
        grants = connection.execute(
            "SELECT user_id, expires_at FROM event_user_access WHERE event_id = ? ORDER BY user_id",
            (target.event_id,),
        ).fetchall()
        assert [(row["user_id"], row["expires_at"]) for row in grants] == [("common", 400)]
