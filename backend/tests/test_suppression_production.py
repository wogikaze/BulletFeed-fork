from app.services.knowledge_evidence import KIND_ALREADY_KNEW, append_knowledge_evidence
from app.services.knowledge_identity import (
    fingerprint_claim,
    map_claim_to_knowledge,
    persist_knowledge_identity,
)
from app.services.relation import RELATION_FEATURE_VERSION
from app.stores.feed_store import FeedStore


def _seed_feed_item(
    connection,
    *,
    item_id: str,
    event_id: str,
    delta_id: str,
    claim_id: str,
    title: str,
    delta_type: str = "new_fact",
) -> None:
    connection.execute(
        """
        INSERT INTO events (
            id, title, summary, current_phase, current_summary,
            current_since, current_confidence, updated_at
        ) VALUES (?, ?, 'summary', 'identified', 'summary',
                  '2026-08-22T00:00:00Z', 'high', '2026-08-22T00:00:00Z')
        """,
        (event_id, title),
    )
    connection.execute(
        """
        INSERT INTO deltas (
            id, event_id, type, summary, before_text, after_text, occurred_at, active
        ) VALUES (?, ?, ?, 'summary', '', 'after', '2026-08-22T00:00:00Z', 1)
        """,
        (delta_id, event_id, delta_type),
    )
    observation_id = f"obs_{claim_id}"
    connection.execute(
        """
        INSERT INTO observations (
            id, source_type, source_key, source_observation_id,
            payload_hash, payload_json, original_url, retrieved_at
        ) VALUES (?, 'statuspage', 'abcd1234', ?, 'hash', '{}',
                  'https://example.test/obs', '2026-08-22T00:00:00Z')
        """,
        (observation_id, observation_id),
    )
    connection.execute(
        """
        INSERT INTO ledger_events (
            id, source_type, source_key, source_event_id, title, created_at
        ) VALUES (?, 'statuspage', 'abcd1234', ?, ?, '2026-08-22T00:00:00Z')
        """,
        (event_id, event_id, title),
    )
    connection.execute(
        """
        INSERT INTO state_claims (
            id, event_id, observation_id, slot, value_text, detail_text,
            valid_at, observed_at
        ) VALUES (?, ?, ?, 'status', 'investigating', 'Investigating elevated latency.',
                  '2026-08-22T00:00:00Z', '2026-08-22T00:00:00Z')
        """,
        (claim_id, event_id, observation_id),
    )
    connection.execute(
        "INSERT INTO delta_claim_map (delta_id, claim_id, event_id) VALUES (?, ?, ?)",
        (delta_id, claim_id, event_id),
    )
    connection.execute(
        """
        INSERT INTO feed_items (
            id, user_id, event_id, delta_id, title, importance_level, importance_reason,
            importance_confidence, relation_level, relation_reason, relation_score,
            relation_feature_version, matched_topics_json, matched_repos_json,
            personalization_rank, status, dismissed, marked_important, updated_at
        ) VALUES (
            ?, 'user_sup', ?, ?, ?, 'medium', 'seed', 'medium', 'adjacent',
            'same level', 0.4, ?, '["latency"]', '[]', 200, 'unread', 0, 0,
            '2026-08-22T00:00:00Z'
        )
        """,
        (item_id, event_id, delta_id, title, RELATION_FEATURE_VERSION),
    )


def test_feed_hides_only_confident_known_same_target(database) -> None:
    with database.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES ('user_sup', 0)")
        _seed_feed_item(
            connection,
            item_id="fi_known",
            event_id="event_known",
            delta_id="delta_known",
            claim_id="claim_known",
            title="Known adjacent",
        )
        _seed_feed_item(
            connection,
            item_id="fi_unknown",
            event_id="event_unknown",
            delta_id="delta_unknown",
            claim_id="claim_unknown",
            title="Unknown adjacent",
        )
        _seed_feed_item(
            connection,
            item_id="fi_fix",
            event_id="event_fix",
            delta_id="delta_fix",
            claim_id="claim_fix",
            title="Correction adjacent",
            delta_type="correction",
        )
        fingerprint = fingerprint_claim(
            value="investigating",
            detail="Investigating elevated latency.",
            slot="status",
        )
        persist_knowledge_identity(connection, fingerprint, created_at=1)
        for claim_id in ("claim_known", "claim_fix"):
            map_claim_to_knowledge(
                connection,
                claim_id=claim_id,
                knowledge_id=fingerprint.identity_id,
                reason="confident same target",
                confidence="high",
                decision="equivalent",
                created_at=1,
            )
        append_knowledge_evidence(
            connection,
            user_id="user_sup",
            kind=KIND_ALREADY_KNEW,
            source_id="fb_known",
            claim_id="claim_known",
            event_id="event_known",
            created_at=2,
        )
        append_knowledge_evidence(
            connection,
            user_id="user_sup",
            kind=KIND_ALREADY_KNEW,
            source_id="fb_fix",
            claim_id="claim_fix",
            event_id="event_fix",
            created_at=2,
        )

    first, _ = FeedStore(database).list_feed(
        "user_sup",
        relation=None,
        item_status=None,
        cursor=None,
        limit=10,
    )
    second, _ = FeedStore(database).list_feed(
        "user_sup",
        relation=None,
        item_status=None,
        cursor=None,
        limit=10,
    )
    ids = [item.id for item in first]
    assert "fi_unknown" in ids
    assert "fi_fix" in ids
    assert "fi_known" not in ids
    assert [item.id for item in second] == ids
