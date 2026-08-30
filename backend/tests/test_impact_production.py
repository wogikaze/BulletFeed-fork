import json

from app.services.knowledge_evidence import CONFIDENCE_NONE, STATE_UNKNOWN
from app.services.relation import RELATION_FEATURE_VERSION
from app.stores.feed_store import _candidate_from_feed_row


def _seed(
    connection,
    *,
    item_id: str,
    event_id: str,
    claim_id: str,
    payload: dict,
    title: str,
) -> None:
    observation_id = f"obs_{claim_id}"
    connection.execute(
        """
        INSERT INTO events (
            id, title, summary, current_phase, current_summary,
            current_since, current_confidence, updated_at
        ) VALUES (?, ?, 'advisory', 'identified', 'advisory',
                  '2026-08-22T00:00:00Z', 'high', '2026-08-22T00:00:00Z')
        """,
        (event_id, title),
    )
    connection.execute(
        """
        INSERT INTO deltas (
            id, event_id, type, summary, before_text, after_text, occurred_at, active
        ) VALUES (?, ?, 'new_fact', 'advisory', '', 'affected', '2026-08-22T00:00:00Z', 1)
        """,
        (f"delta_{claim_id}", event_id),
    )
    connection.execute(
        """
        INSERT INTO observations (
            id, source_type, source_key, source_observation_id,
            payload_hash, payload_json, original_url, retrieved_at
        ) VALUES (?, 'github_advisory', 'GHSA-demo', ?, 'hash', ?,
                  'https://github.com/advisories/GHSA-demo', '2026-08-22T00:00:00Z')
        """,
        (observation_id, observation_id, json.dumps(payload)),
    )
    connection.execute(
        """
        INSERT INTO ledger_events (
            id, source_type, source_key, source_event_id, title, created_at
        ) VALUES (?, 'github_advisory', 'GHSA-demo', ?, ?, '2026-08-22T00:00:00Z')
        """,
        (event_id, event_id, title),
    )
    connection.execute(
        """
        INSERT INTO state_claims (
            id, event_id, observation_id, slot, value_text, detail_text,
            valid_at, observed_at
        ) VALUES (?, ?, ?, 'dependency_vulnerability', 'affected',
                  'example 1.0.0 is affected', '2026-08-22T00:00:00Z', '2026-08-22T00:00:00Z')
        """,
        (claim_id, event_id, observation_id),
    )
    connection.execute(
        "INSERT INTO delta_claim_map (delta_id, claim_id, event_id) VALUES (?, ?, ?)",
        (f"delta_{claim_id}", claim_id, event_id),
    )
    connection.execute(
        """
        INSERT INTO feed_items (
            id, user_id, event_id, delta_id, title, importance_level, importance_reason,
            importance_confidence, relation_level, relation_reason, relation_score,
            relation_feature_version, matched_topics_json, matched_repos_json,
            personalization_rank, status, dismissed, marked_important, updated_at
        ) VALUES (
            ?, 'user_imp', ?, ?, ?, 'medium', 'seed', 'medium', 'adjacent',
            'same level', 0.4, ?, '["security"]', '[]', 200, 'unread', 0, 0,
            '2026-08-22T00:00:00Z'
        )
        """,
        (item_id, event_id, f"delta_{claim_id}", title, RELATION_FEATURE_VERSION),
    )


def _row_for(connection, item_id: str):
    return connection.execute(
        """
        SELECT f.*, d.type AS delta_type, d.summary AS delta_summary,
               COALESCE(le.source_type, 'unknown') AS source_type,
               COALESCE(le.source_key, '') AS source_key,
               COALESCE(e.summary, '') AS event_summary,
               COALESCE(sc.value_text, '') AS claim_value,
               COALESCE(sc.detail_text, '') AS claim_detail,
               obs.payload_json AS observation_payload,
               claim_map.claim_id AS claim_id
        FROM feed_items f
        JOIN deltas d ON d.id = f.delta_id
        LEFT JOIN events e ON e.id = f.event_id
        LEFT JOIN ledger_events le ON le.id = f.event_id
        LEFT JOIN delta_claim_map claim_map ON claim_map.delta_id = f.delta_id
        LEFT JOIN state_claims sc ON sc.id = claim_map.claim_id
        LEFT JOIN observations obs ON obs.id = sc.observation_id
        WHERE f.id = ?
        """,
        (item_id,),
    ).fetchone()


def test_production_ranking_uses_observation_payload_not_title_only(database) -> None:
    with database.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES ('user_imp', 0)")
        _seed(
            connection,
            item_id="fi_lossy",
            event_id="event_lossy",
            claim_id="claim_lossy",
            payload={},
            title="Advisory for example",
        )
        _seed(
            connection,
            item_id="fi_structured",
            event_id="event_structured",
            claim_id="claim_structured",
            payload={
                "severity": "critical",
                "cvss": {"vector_string": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"},
                "affected": [{"package": {"name": "example"}}],
            },
            title="Advisory for example",
        )
        lossy = _candidate_from_feed_row(
            connection,
            user_id="user_imp",
            row=_row_for(connection, "fi_lossy"),
            knownness=(STATE_UNKNOWN, CONFIDENCE_NONE),
        )
        structured = _candidate_from_feed_row(
            connection,
            user_id="user_imp",
            row=_row_for(connection, "fi_structured"),
            knownness=(STATE_UNKNOWN, CONFIDENCE_NONE),
        )
    assert lossy.impact_snapshot["signals"]["security_severity"]["value"] == "unknown"
    assert structured.impact_snapshot["signals"]["security_severity"]["value"] == "critical"
    assert structured.impact_snapshot["signals"]["security_severity"]["source_field"] == "payload.severity"
    assert structured.impact_snapshot["signals"]["affected_packages"]["value"]
