from pathlib import Path

from app.database import Database
from app.db.migrations import KNOWN_REVISIONS
from app.services.feed_projection import FeedProjector
from app.services.ranking import evaluate_importance
from app.services.ranking_feedback import (
    MIN_SAMPLE_SIZE,
    PERSONALIZATION_VERSION,
    apply_feedback_ranking,
    reset_feedback_ranking,
)
from app.services.statuspage_pipeline import StatuspagePipeline


def _rank_key(row) -> tuple[int, int, int, str, str]:
    importance = {"critical": 4, "high": 3, "medium": 2, "low": 1}[row["importance_level"]]
    relation = {"direct": 3, "adjacent": 2, "reference": 1}[row["relation_level"]]
    return (
        importance,
        relation,
        int(row["personalization_rank"]),
        row["updated_at"],
        row["id"],
    )


def _ordered_ids(connection, user_id: str) -> list[str]:
    rows = connection.execute(
        """
        SELECT id, importance_level, relation_level, personalization_rank, updated_at
        FROM feed_items
        WHERE user_id = ?
        """,
        (user_id,),
    ).fetchall()
    return [row["id"] for row in sorted(rows, key=_rank_key, reverse=True)]


def _insert_item(
    connection,
    *,
    user_id: str,
    item_id: str,
    event_id: str,
    source_type: str,
    updated_at: str,
    delta_type: str = "detail",
    title: str | None = None,
    source_key: str | None = None,
) -> None:
    connection.execute("INSERT OR IGNORE INTO users (id, created_at) VALUES (?, 0)", (user_id,))
    event_title = title or f"{source_type} {event_id}"
    connection.execute(
        """
        INSERT INTO events (
            id, title, summary, current_phase, current_summary,
            current_since, current_confidence, updated_at
        ) VALUES (?, ?, '', 'published', '', ?, 'high', ?)
        """,
        (event_id, event_title, updated_at, updated_at),
    )
    connection.execute(
        """
        INSERT INTO ledger_events (
            id, source_type, source_key, source_event_id, title, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (event_id, source_type, source_key or event_id, event_id, event_id, updated_at),
    )
    delta_id = f"d_{item_id}"
    connection.execute(
        """
        INSERT INTO deltas (
            id, event_id, type, summary, before_text, after_text, occurred_at
        ) VALUES (?, ?, ?, '', '', '', ?)
        """,
        (delta_id, event_id, delta_type, updated_at),
    )
    importance = evaluate_importance(source_type=source_type, delta_type=delta_type)
    connection.execute(
        """
        INSERT INTO feed_items (
            id, user_id, event_id, delta_id, title,
            importance_level, importance_reason, importance_confidence,
            relation_level, relation_reason, matched_topics_json,
            matched_repos_json, personalization_rank,
            status, dismissed, marked_important, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'reference', '', '[]', '[]', 0, 'unread', 0, 0, ?)
        """,
        (
            item_id,
            user_id,
            event_id,
            delta_id,
            event_id,
            importance.level,
            importance.reason,
            importance.confidence,
            updated_at,
        ),
    )


def _mark(connection, *, user_id: str, item_id: str, feedback_type: str, created_at: int) -> None:
    connection.execute(
        """
        INSERT INTO feedback (id, feed_item_id, user_id, type, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (f"fb_{item_id}_{feedback_type}_{created_at}", item_id, user_id, feedback_type, created_at),
    )


def _held_out_fixture(database: Database) -> None:
    with database.connect() as connection:
        for index in range(MIN_SAMPLE_SIZE):
            _insert_item(
                connection,
                user_id="learner",
                item_id=f"train_{index}",
                event_id=f"ev_train_{index}",
                source_type="github_release",
                updated_at=f"2026-08-20T00:0{index}:00Z",
            )
        _insert_item(
            connection,
            user_id="learner",
            item_id="held_release",
            event_id="ev_held_release",
            source_type="github_release",
            updated_at="2026-08-21T00:00:00Z",
        )
        _insert_item(
            connection,
            user_id="learner",
            item_id="held_rss",
            event_id="ev_held_rss",
            source_type="rss_atom",
            updated_at="2026-08-22T00:00:00Z",
            delta_type="new_fact",
        )
        _insert_item(
            connection,
            user_id="other",
            item_id="other_release",
            event_id="ev_other_release",
            source_type="github_release",
            updated_at="2026-08-21T00:00:00Z",
        )


def _snapshot_ledger(database: Database) -> tuple[tuple, tuple]:
    with database.connect() as connection:
        claims = tuple(
            tuple(row)
            for row in connection.execute(
                "SELECT * FROM state_claims ORDER BY id"
            )
        )
        relations = tuple(
            tuple(row)
            for row in connection.execute(
                "SELECT * FROM claim_relations ORDER BY id"
            )
        )
    return claims, relations


def _statuspage_summary() -> dict:
    return {
        "incidents": [
            {
                "id": "inc_rank",
                "name": "API latency",
                "impact": "major",
                "created_at": "2026-08-22T00:00:00Z",
                "shortlink": "https://stspg.io/inc_rank",
                "incident_updates": [
                    {
                        "id": "upd_rank_1",
                        "status": "investigating",
                        "body": "Investigating elevated latency.",
                        "created_at": "2026-08-22T00:00:00Z",
                        "updated_at": "2026-08-22T00:00:00Z",
                        "display_at": "2026-08-22T00:00:00Z",
                    },
                    {
                        "id": "upd_rank_2",
                        "status": "identified",
                        "body": "Database saturation identified.",
                        "created_at": "2026-08-22T00:10:00Z",
                        "updated_at": "2026-08-22T00:10:00Z",
                        "display_at": "2026-08-22T00:10:00Z",
                    },
                ],
            }
        ]
    }


def test_one_click_below_threshold_does_not_move_ranks(database) -> None:
    _held_out_fixture(database)
    with database.connect() as connection:
        before = connection.execute(
            "SELECT importance_level, relation_level FROM feed_items WHERE id = 'held_release'"
        ).fetchone()
        _mark(
            connection,
            user_id="learner",
            item_id="train_0",
            feedback_type="important",
            created_at=10,
        )
        apply_feedback_ranking(connection, user_id="learner")
        after = connection.execute(
            "SELECT importance_level, relation_level, importance_reason, relation_reason "
            "FROM feed_items WHERE id = 'held_release'"
        ).fetchone()

    assert after["importance_level"] == before["importance_level"]
    assert after["relation_level"] == before["relation_level"]
    assert PERSONALIZATION_VERSION not in after["importance_reason"]
    assert PERSONALIZATION_VERSION not in after["relation_reason"]


def test_held_out_order_changes_after_enough_feedback(database) -> None:
    _held_out_fixture(database)
    with database.connect() as connection:
        before = _ordered_ids(connection, "learner")
        assert before.index("held_rss") < before.index("held_release")
        for index in range(MIN_SAMPLE_SIZE):
            _mark(
                connection,
                user_id="learner",
                item_id=f"train_{index}",
                feedback_type="important",
                created_at=20 + index,
            )
        apply_feedback_ranking(connection, user_id="learner")
        after = _ordered_ids(connection, "learner")
        held = connection.execute(
            "SELECT importance_level, importance_reason FROM feed_items WHERE id = 'held_release'"
        ).fetchone()
        rss = connection.execute(
            "SELECT importance_level, importance_reason FROM feed_items WHERE id = 'held_rss'"
        ).fetchone()

    assert after.index("held_release") < after.index("held_rss")
    assert held["importance_level"] == "high"
    assert PERSONALIZATION_VERSION in held["importance_reason"]
    assert "3 important marks on github_release items" in held["importance_reason"]
    assert rss["importance_level"] == "medium"
    assert PERSONALIZATION_VERSION not in rss["importance_reason"]


def test_not_relevant_batch_demotes_relation_with_reason(database) -> None:
    _held_out_fixture(database)
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO topics (id, user_id, name, type, priority, sort_order, created_at)
            VALUES ('topic_release', 'learner', 'github_release', 'technology', 'normal', 0, 0)
            """
        )
        apply_feedback_ranking(connection, user_id="learner")
        baseline = connection.execute(
            "SELECT relation_level FROM feed_items WHERE id = 'held_release'"
        ).fetchone()
        assert baseline["relation_level"] == "adjacent"
        for index in range(MIN_SAMPLE_SIZE):
            _mark(
                connection,
                user_id="learner",
                item_id=f"train_{index}",
                feedback_type="not_relevant",
                created_at=30 + index,
            )
        apply_feedback_ranking(connection, user_id="learner")
        held = connection.execute(
            "SELECT relation_level, relation_reason FROM feed_items WHERE id = 'held_release'"
        ).fetchone()
        other = connection.execute(
            "SELECT relation_level, relation_reason FROM feed_items WHERE id = 'other_release'"
        ).fetchone()

    assert held["relation_level"] == "reference"
    assert PERSONALIZATION_VERSION in held["relation_reason"]
    assert "3 not_relevant marks on github_release items" in held["relation_reason"]
    assert other["relation_level"] == "reference"
    assert PERSONALIZATION_VERSION not in other["relation_reason"]


def test_feedback_ranking_is_per_user_and_resettable(database) -> None:
    _held_out_fixture(database)
    with database.connect() as connection:
        for index in range(MIN_SAMPLE_SIZE):
            _mark(
                connection,
                user_id="learner",
                item_id=f"train_{index}",
                feedback_type="important",
                created_at=40 + index,
            )
        apply_feedback_ranking(connection, user_id="learner")
        apply_feedback_ranking(connection, user_id="other")
        learner = connection.execute(
            "SELECT importance_level FROM feed_items WHERE id = 'held_release'"
        ).fetchone()
        other = connection.execute(
            "SELECT importance_level FROM feed_items WHERE id = 'other_release'"
        ).fetchone()
        assert learner["importance_level"] == "high"
        assert other["importance_level"] == "medium"

        reset_feedback_ranking(connection, user_id="learner", reset_at=100)
        restored = connection.execute(
            "SELECT importance_level, importance_reason FROM feed_items WHERE id = 'held_release'"
        ).fetchone()
        leftover = connection.execute(
            "SELECT important_count FROM user_ranking_features WHERE user_id = 'learner'"
        ).fetchone()

    assert restored["importance_level"] == "medium"
    assert PERSONALIZATION_VERSION not in restored["importance_reason"]
    assert leftover is None


def test_concept_feedback_lifts_same_source_type_held_out(database) -> None:
    with database.connect() as connection:
        for index in range(MIN_SAMPLE_SIZE):
            _insert_item(
                connection,
                user_id="learner",
                item_id=f"train_react_{index}",
                event_id=f"ev_train_react_{index}",
                source_type="github_release",
                updated_at=f"2026-08-20T00:0{index}:00Z",
                title=f"React 19 train {index}",
            )
            _mark(
                connection,
                user_id="learner",
                item_id=f"train_react_{index}",
                feedback_type="important",
                created_at=40 + index,
            )
        _insert_item(
            connection,
            user_id="learner",
            item_id="held_react",
            event_id="ev_held_react",
            source_type="rss_atom",
            updated_at="2026-08-21T00:00:00Z",
            title="React 19 release",
        )
        _insert_item(
            connection,
            user_id="learner",
            item_id="held_other",
            event_id="ev_held_other",
            source_type="rss_atom",
            updated_at="2026-08-22T00:00:00Z",
            title="PostgreSQL 18 notes",
        )
        apply_feedback_ranking(connection, user_id="learner")
        held = connection.execute(
            "SELECT importance_level, importance_reason FROM feed_items WHERE id = 'held_react'"
        ).fetchone()
        other = connection.execute(
            "SELECT importance_level, importance_reason FROM feed_items WHERE id = 'held_other'"
        ).fetchone()
        concept = connection.execute(
            """
            SELECT important_count FROM user_ranking_features
            WHERE user_id = 'learner' AND feature_kind = 'concept' AND feature_value = 'react'
            """
        ).fetchone()

    assert concept is not None
    assert concept["important_count"] == MIN_SAMPLE_SIZE
    assert held["importance_level"] == "high"
    assert PERSONALIZATION_VERSION in held["importance_reason"]
    assert "react" in held["importance_reason"]
    assert other["importance_level"] == "medium"
    assert PERSONALIZATION_VERSION not in other["importance_reason"]


def test_topic_feedback_lifts_same_source_type_held_out(database) -> None:
    with database.connect() as connection:
        connection.execute("INSERT OR IGNORE INTO users (id, created_at) VALUES ('learner', 0)")
        connection.execute(
            """
            INSERT INTO topics (id, user_id, name, type, priority, sort_order, created_at)
            VALUES ('topic_kotlin', 'learner', 'Kotlin', 'technology', 'high', 0, 0)
            """
        )
        for index in range(MIN_SAMPLE_SIZE):
            _insert_item(
                connection,
                user_id="learner",
                item_id=f"train_kotlin_{index}",
                event_id=f"ev_train_kotlin_{index}",
                source_type="github_release",
                updated_at=f"2026-08-20T00:0{index}:00Z",
                title=f"Kotlin 2.1 train {index}",
            )
            _mark(
                connection,
                user_id="learner",
                item_id=f"train_kotlin_{index}",
                feedback_type="important",
                created_at=40 + index,
            )
        _insert_item(
            connection,
            user_id="learner",
            item_id="held_kotlin",
            event_id="ev_held_kotlin",
            source_type="rss_atom",
            updated_at="2026-08-21T00:00:00Z",
            title="Kotlin 2.1 notes",
        )
        _insert_item(
            connection,
            user_id="learner",
            item_id="held_other",
            event_id="ev_held_other",
            source_type="rss_atom",
            updated_at="2026-08-22T00:00:00Z",
            title="PostgreSQL 18 notes",
        )
        apply_feedback_ranking(connection, user_id="learner")
        held = connection.execute(
            "SELECT importance_level, importance_reason FROM feed_items WHERE id = 'held_kotlin'"
        ).fetchone()
        other = connection.execute(
            "SELECT importance_level, importance_reason FROM feed_items WHERE id = 'held_other'"
        ).fetchone()
        topic = connection.execute(
            """
            SELECT important_count FROM user_ranking_features
            WHERE user_id = 'learner' AND feature_kind = 'topic' AND feature_value = 'Kotlin'
            """
        ).fetchone()

    assert topic is not None
    assert topic["important_count"] == MIN_SAMPLE_SIZE
    assert held["importance_level"] == "high"
    assert PERSONALIZATION_VERSION in held["importance_reason"]
    assert "Kotlin" in held["importance_reason"]
    assert other["importance_level"] == "medium"
    assert PERSONALIZATION_VERSION not in other["importance_reason"]


def test_repository_feedback_lifts_held_out_without_source_type_threshold(database) -> None:
    with database.connect() as connection:
        connection.execute("INSERT OR IGNORE INTO users (id, created_at) VALUES ('learner', 0)")
        connection.execute(
            """
            INSERT INTO github_repo_watches (
                user_id, repository_id, full_name, html_url, selected, private
            ) VALUES ('learner', 'repo-react', 'facebook/react', 'https://github.com/facebook/react', 1, 0)
            """
        )
        for index, source_type in enumerate(("github_release", "github_advisory", "osv")):
            _insert_item(
                connection,
                user_id="learner",
                item_id=f"train_repo_{index}",
                event_id=f"ev_train_repo_{index}",
                source_type=source_type,
                source_key="facebook/react",
                updated_at=f"2026-08-20T00:0{index}:00Z",
                title=f"Unrelated kitchen notes {index}",
            )
            _mark(
                connection,
                user_id="learner",
                item_id=f"train_repo_{index}",
                feedback_type="important",
                created_at=40 + index,
            )
        _insert_item(
            connection,
            user_id="learner",
            item_id="held_react_repo",
            event_id="ev_held_react_repo",
            source_type="github_release",
            source_key="facebook/react",
            updated_at="2026-08-21T00:00:00Z",
            title="Unrelated desk lamp manual",
        )
        _insert_item(
            connection,
            user_id="learner",
            item_id="held_go_repo",
            event_id="ev_held_go_repo",
            source_type="github_release",
            source_key="golang/go",
            updated_at="2026-08-22T00:00:00Z",
            title="Unrelated garden hose specs",
        )
        apply_feedback_ranking(connection, user_id="learner")
        held = connection.execute(
            "SELECT importance_level, importance_reason FROM feed_items WHERE id = 'held_react_repo'"
        ).fetchone()
        other = connection.execute(
            "SELECT importance_level, importance_reason FROM feed_items WHERE id = 'held_go_repo'"
        ).fetchone()
        repo = connection.execute(
            """
            SELECT important_count FROM user_ranking_features
            WHERE user_id = 'learner' AND feature_kind = 'repository'
              AND feature_value = 'facebook/react'
            """
        ).fetchone()

    assert repo is not None
    assert repo["important_count"] == MIN_SAMPLE_SIZE
    assert held["importance_level"] == "high"
    assert PERSONALIZATION_VERSION in held["importance_reason"]
    assert "facebook/react" in held["importance_reason"]
    assert other["importance_level"] == "medium"
    assert PERSONALIZATION_VERSION not in other["importance_reason"]


def test_impact_feedback_lifts_same_source_type_held_out(database) -> None:
    with database.connect() as connection:
        for index, source_type in enumerate(("rss_atom", "github_release", "package_registry")):
            _insert_item(
                connection,
                user_id="learner",
                item_id=f"train_impact_{index}",
                event_id=f"ev_train_impact_{index}",
                source_type=source_type,
                updated_at=f"2026-08-20T00:0{index}:00Z",
                delta_type="state_update",
                title=f"Unrelated kitchen notes {index}",
            )
            _mark(
                connection,
                user_id="learner",
                item_id=f"train_impact_{index}",
                feedback_type="important",
                created_at=40 + index,
            )
        _insert_item(
            connection,
            user_id="learner",
            item_id="held_state",
            event_id="ev_held_state",
            source_type="rss_atom",
            updated_at="2026-08-21T00:00:00Z",
            delta_type="state_update",
            title="Unrelated desk lamp manual",
        )
        _insert_item(
            connection,
            user_id="learner",
            item_id="held_other",
            event_id="ev_held_other",
            source_type="rss_atom",
            updated_at="2026-08-22T00:00:00Z",
            title="Unrelated garden hose specs",
        )
        apply_feedback_ranking(connection, user_id="learner")
        held = connection.execute(
            "SELECT importance_level, importance_reason FROM feed_items WHERE id = 'held_state'"
        ).fetchone()
        other = connection.execute(
            "SELECT importance_level, importance_reason FROM feed_items WHERE id = 'held_other'"
        ).fetchone()
        impact = connection.execute(
            """
            SELECT important_count FROM user_ranking_features
            WHERE user_id = 'learner' AND feature_kind = 'impact' AND feature_value = 'state_update'
            """
        ).fetchone()

    assert impact is not None
    assert impact["important_count"] == MIN_SAMPLE_SIZE
    assert held["importance_level"] == "high"
    assert PERSONALIZATION_VERSION in held["importance_reason"]
    assert "state_update" in held["importance_reason"]
    assert other["importance_level"] == "medium"
    assert PERSONALIZATION_VERSION not in other["importance_reason"]


def test_replay_matches_with_and_without_feedback(tmp_path: Path) -> None:
    clean = Database(tmp_path / "clean.db")
    clean.initialize()
    noisy = Database(tmp_path / "noisy.db")
    noisy.initialize()

    StatuspagePipeline(clean).ingest_summary(
        page_id="abcd1234",
        summary=_statuspage_summary(),
        retrieved_at="2026-08-22T00:11:00Z",
    )
    result = StatuspagePipeline(noisy).ingest_summary(
        page_id="abcd1234",
        summary=_statuspage_summary(),
        retrieved_at="2026-08-22T00:11:00Z",
    )
    event_id = result.event_ids[0]
    with noisy.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES ('learner', 0)")
    FeedProjector(noisy).project_event_for_user(user_id="learner", event_id=event_id)
    with noisy.connect() as connection:
        item_id = connection.execute(
            "SELECT id FROM feed_items WHERE user_id = 'learner' LIMIT 1"
        ).fetchone()["id"]
        _mark(
            connection,
            user_id="learner",
            item_id=item_id,
            feedback_type="important",
            created_at=1,
        )
        apply_feedback_ranking(connection, user_id="learner")

    assert _snapshot_ledger(clean) == _snapshot_ledger(noisy)
    assert _snapshot_ledger(clean)[0]
    assert _snapshot_ledger(clean)[1]


def test_revision_6_adds_ranking_feature_tables(tmp_path: Path) -> None:
    database = Database(tmp_path / "pre-ranking-features.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute("DELETE FROM schema_migrations WHERE revision_id = '6'")
        connection.execute("DROP TABLE user_ranking_features")
        connection.execute("DROP TABLE user_ranking_resets")

    database.initialize()

    with database.connect() as connection:
        revisions = {
            row[0] for row in connection.execute("SELECT revision_id FROM schema_migrations")
        }
        assert revisions == set(KNOWN_REVISIONS)
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'user_ranking_features'"
        ).fetchone()
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'user_ranking_resets'"
        ).fetchone()
