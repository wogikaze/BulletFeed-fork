from app.services.knowledge_identity import (
    fingerprint_claim,
    map_claim_to_knowledge,
    persist_knowledge_identity,
)
from app.services.relation import RELATION_FEATURE_VERSION
from app.stores.feed_store import FeedStore


def _seed_card(
    connection,
    *,
    user_id: str,
    item_id: str,
    event_id: str,
    delta_id: str,
    claim_id: str,
    title: str,
    source_type: str,
    source_key: str,
    publisher: str,
    kind: str,
    url: str,
    value: str = "investigating",
    detail: str = "Investigating elevated latency.",
    delta_type: str = "new_fact",
    published_at: str = "2026-08-22T00:00:00Z",
) -> None:
    connection.execute(
        """
        INSERT INTO events (
            id, title, summary, current_phase, current_summary,
            current_since, current_confidence, updated_at
        ) VALUES (?, ?, ?, 'identified', ?, ?, 'high', ?)
        """,
        (event_id, title, detail, detail, published_at, published_at),
    )
    connection.execute(
        """
        INSERT INTO deltas (
            id, event_id, type, summary, before_text, after_text, occurred_at, active
        ) VALUES (?, ?, ?, ?, '', ?, ?, 1)
        """,
        (delta_id, event_id, delta_type, detail, value, published_at),
    )
    observation_id = f"obs_{claim_id}"
    connection.execute(
        """
        INSERT INTO observations (
            id, source_type, source_key, source_observation_id,
            payload_hash, payload_json, original_url, retrieved_at
        ) VALUES (?, ?, ?, ?, 'hash', '{}', ?, ?)
        """,
        (observation_id, source_type, source_key, observation_id, url, published_at),
    )
    connection.execute(
        """
        INSERT INTO ledger_events (
            id, source_type, source_key, source_event_id, title, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (event_id, source_type, source_key, event_id, title, published_at),
    )
    connection.execute(
        """
        INSERT INTO state_claims (
            id, event_id, observation_id, slot, value_text, detail_text,
            valid_at, observed_at
        ) VALUES (?, ?, ?, 'status', ?, ?, ?, ?)
        """,
        (claim_id, event_id, observation_id, value, detail, published_at, published_at),
    )
    connection.execute(
        "INSERT INTO delta_claim_map (delta_id, claim_id, event_id) VALUES (?, ?, ?)",
        (delta_id, claim_id, event_id),
    )
    connection.execute(
        """
        INSERT INTO event_sources (
            id, event_id, publisher, kind, title, url, published_at, retrieved_at, evidence
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (f"src_{event_id}", event_id, publisher, kind, title, url, published_at, published_at, detail),
    )
    connection.execute(
        """
        INSERT INTO feed_items (
            id, user_id, event_id, delta_id, title, importance_level, importance_reason,
            importance_confidence, relation_level, relation_reason, relation_score,
            relation_feature_version, matched_topics_json, matched_repos_json,
            personalization_rank, status, dismissed, marked_important, updated_at
        ) VALUES (
            ?, ?, ?, ?, ?, 'medium', 'seed', 'medium', 'adjacent',
            'same level', 0.4, ?, '["latency"]', '[]', 200, 'unread', 0, 0, ?
        )
        """,
        (item_id, user_id, event_id, delta_id, title, RELATION_FEATURE_VERSION, published_at),
    )


def test_same_fact_later_source_becomes_additional_sources(database, client, auth_headers) -> None:
    with database.connect() as connection:
        user = connection.execute(
            "SELECT id FROM users WHERE github_user_id = 123"
        ).fetchone()
        assert user is not None
        user_id = user["id"]
        _seed_card(
            connection,
            user_id=user_id,
            item_id="fi_status",
            event_id="event_status",
            delta_id="delta_status",
            claim_id="claim_status",
            title="Elevated latency",
            source_type="statuspage",
            source_key="acme",
            publisher="Acme Status",
            kind="statuspage",
            url="https://status.acme.test/incidents/1",
            published_at="2026-08-22T00:00:00Z",
        )
        _seed_card(
            connection,
            user_id=user_id,
            item_id="fi_rss",
            event_id="event_rss",
            delta_id="delta_rss",
            claim_id="claim_rss",
            title="Acme investigating latency",
            source_type="rss_atom",
            source_key="news",
            publisher="News Wire",
            kind="rss_atom",
            url="https://news.example/acme-latency",
            published_at="2026-08-22T00:05:00Z",
        )
        fingerprint = fingerprint_claim(
            value="investigating",
            detail="Investigating elevated latency.",
            slot="status",
        )
        persist_knowledge_identity(connection, fingerprint, created_at=1)
        for claim_id in ("claim_status", "claim_rss"):
            map_claim_to_knowledge(
                connection,
                claim_id=claim_id,
                knowledge_id=fingerprint.identity_id,
                reason="same investigating status",
                confidence="high",
                decision="equivalent",
                created_at=1,
            )

    response = client.get("/v1/feed", headers=auth_headers, params={"limit": 20})
    assert response.status_code == 200
    payload = response.json()
    ids = [item["id"] for item in payload["items"]]
    assert "fi_status" in ids
    assert "fi_rss" not in ids
    card = next(item for item in payload["items"] if item["id"] == "fi_status")
    assert card["additionalSources"]
    assert card["additionalSources"][0]["publisher"] == "News Wire"
    assert card["additionalSources"][0]["kind"] == "rss_atom"


def test_correction_does_not_collapse_onto_prior_card(database) -> None:
    with database.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES ('user_xs', 0)")
        _seed_card(
            connection,
            user_id="user_xs",
            item_id="fi_old",
            event_id="event_old",
            delta_id="delta_old",
            claim_id="claim_old",
            title="Identified",
            source_type="statuspage",
            source_key="acme",
            publisher="Acme Status",
            kind="statuspage",
            url="https://status.acme.test/incidents/1",
            value="investigating",
            detail="Investigating elevated latency.",
        )
        _seed_card(
            connection,
            user_id="user_xs",
            item_id="fi_fix",
            event_id="event_fix",
            delta_id="delta_fix",
            claim_id="claim_fix",
            title="Corrected",
            source_type="statuspage",
            source_key="acme",
            publisher="Acme Status",
            kind="statuspage",
            url="https://status.acme.test/incidents/1b",
            value="resolved",
            detail="Latency is resolved.",
            delta_type="correction",
            published_at="2026-08-22T01:00:00Z",
        )

    items, _ = FeedStore(database).list_feed(
        "user_xs",
        relation=None,
        item_status=None,
        cursor=None,
        limit=10,
    )
    ids = [item.id for item in items]
    assert "fi_old" in ids
    assert "fi_fix" in ids
    assert all(not item.additional_sources for item in items)


def test_uncertain_identity_does_not_hide_or_collapse(database) -> None:
    with database.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES ('user_unc', 0)")
        _seed_card(
            connection,
            user_id="user_unc",
            item_id="fi_a",
            event_id="event_a",
            delta_id="delta_a",
            claim_id="claim_a",
            title="Maybe related A",
            source_type="rss_atom",
            source_key="wire-a",
            publisher="Wire A",
            kind="rss_atom",
            url="https://a.example/1",
            value="possible outage",
            detail="Reports of an outage are unconfirmed.",
        )
        _seed_card(
            connection,
            user_id="user_unc",
            item_id="fi_b",
            event_id="event_b",
            delta_id="delta_b",
            claim_id="claim_b",
            title="Maybe related B",
            source_type="rss_atom",
            source_key="wire-b",
            publisher="Wire B",
            kind="rss_atom",
            url="https://b.example/2",
            value="network issue",
            detail="A different network issue may be happening.",
        )

    items, _ = FeedStore(database).list_feed(
        "user_unc",
        relation=None,
        item_status=None,
        cursor=None,
        limit=10,
    )
    ids = {item.id for item in items}
    assert ids == {"fi_a", "fi_b"}
