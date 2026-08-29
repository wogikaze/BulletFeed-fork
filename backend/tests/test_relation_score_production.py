from app.services.feed_projection import FeedProjector
from app.services.ledger_projection import LedgerProjector
from app.services.relation import RELATION_FEATURE_VERSION, evaluate_relation
from app.services.statuspage_pipeline import StatuspagePipeline
from app.stores.feed_store import FeedStore


def _summary():
    return {
        "incidents": [
            {
                "id": "inc_rel_score",
                "name": "API latency",
                "impact": "major",
                "created_at": "2026-08-22T00:00:00Z",
                "shortlink": "https://stspg.io/inc_rel_score",
                "incident_updates": [
                    {
                        "id": "upd_rel_score_1",
                        "status": "investigating",
                        "body": "Investigating elevated latency.",
                        "created_at": "2026-08-22T00:00:00Z",
                        "updated_at": "2026-08-22T00:00:00Z",
                        "display_at": "2026-08-22T00:00:00Z",
                    }
                ],
            }
        ]
    }


def test_projection_persists_versioned_relation_score(database) -> None:
    result = StatuspagePipeline(database).ingest_summary(
        page_id="abcd1234",
        summary=_summary(),
        retrieved_at="2026-08-22T00:11:00Z",
    )
    event_id = result.event_ids[0]
    LedgerProjector(database).project_event(event_id)
    with database.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES ('user_1', 0)")
        connection.execute(
            """
            INSERT INTO topics (id, user_id, name, type, priority, sort_order, created_at)
            VALUES ('topic_1', 'user_1', 'latency', 'technology', 'high', 0, 0)
            """
        )
        expected = evaluate_relation(
            connection,
            user_id="user_1",
            source_type="statuspage",
            source_key="abcd1234",
            event_title="API latency",
            event_summary="Investigating elevated latency.",
        )

    FeedProjector(database).project_event_for_user(user_id="user_1", event_id=event_id)

    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT relation_level, relation_score, relation_feature_version
            FROM feed_items WHERE user_id = 'user_1' AND event_id = ?
            """,
            (event_id,),
        ).fetchall()
    assert rows
    assert all(row["relation_feature_version"] == RELATION_FEATURE_VERSION for row in rows)
    assert all(row["relation_score"] == expected.score for row in rows)
    assert all(row["relation_level"] == expected.level for row in rows)


def test_production_ranker_uses_persisted_score_not_zero(database) -> None:
    with database.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES ('user_score', 0)")
        for suffix, title, score in (
            ("weak", "Weak adjacent", 0.21),
            ("strong", "Strong adjacent", 0.84),
        ):
            connection.execute(
                """
                INSERT INTO events (
                    id, title, summary, current_phase, current_summary,
                    current_since, current_confidence, updated_at
                ) VALUES (?, ?, 'summary', 'identified', 'summary',
                          '2026-08-22T00:00:00Z', 'high', '2026-08-22T00:00:00Z')
                """,
                (f"event_{suffix}", title),
            )
            connection.execute(
                """
                INSERT INTO deltas (
                    id, event_id, type, summary, before_text, after_text, occurred_at, active
                ) VALUES (?, ?, 'new_fact', 'summary', '', 'after',
                          '2026-08-22T00:00:00Z', 1)
                """,
                (f"delta_{suffix}", f"event_{suffix}"),
            )
            connection.execute(
                """
                INSERT INTO feed_items (
                    id, user_id, event_id, delta_id, title, importance_level, importance_reason,
                    importance_confidence, relation_level, relation_reason, relation_score,
                    relation_feature_version, matched_topics_json, matched_repos_json,
                    personalization_rank, status, dismissed, marked_important, updated_at
                ) VALUES (
                    ?, 'user_score', ?, ?, ?, 'medium', 'seed', 'medium', 'adjacent',
                    'same level', ?, ?, '["latency"]', '[]', 200, 'unread', 0, 0,
                    '2026-08-22T00:00:00Z'
                )
                """,
                (
                    f"fi_{suffix}",
                    f"event_{suffix}",
                    f"delta_{suffix}",
                    title,
                    score,
                    RELATION_FEATURE_VERSION,
                ),
            )

    store = FeedStore(database)
    first, _ = store.list_feed(
        "user_score",
        relation=None,
        item_status=None,
        cursor=None,
        limit=10,
    )
    second, _ = store.list_feed(
        "user_score",
        relation=None,
        item_status=None,
        cursor=None,
        limit=10,
    )
    assert [item.id for item in first] == ["fi_strong", "fi_weak"]
    assert [item.id for item in second] == ["fi_strong", "fi_weak"]
    assert [item.relation.level for item in first] == ["adjacent", "adjacent"]
