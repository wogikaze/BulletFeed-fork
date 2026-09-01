"""#317: explicit feedback must change the next GET /feed on the same candidates.

Learning lives in ranking overlay only. Event/Claim/Delta rows stay untouched.
One click is not enough; MIN_SAMPLE_SIZE important marks on a source type
must lift held-out siblings of that type on the following feed page.
"""

from __future__ import annotations

import math
import time

from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import Database
from app.security import TokenCipher
from app.services.feedback_signals import (
    assert_feedback_does_not_mutate_ledger,
    ledger_world_state,
)
from app.services.ranking import evaluate_importance
from app.services.ranking_feedback import MIN_SAMPLE_SIZE, PERSONALIZATION_VERSION

_HELD_K = 5
_HELD_RELEVANT = tuple(f"nfeed_ho_rel_{index}" for index in range(4))
_HELD_NOISE = tuple(f"nfeed_ho_noise_{index}" for index in range(4))
_HELD_UNKNOWN = "nfeed_ho_unknown"
_HELD_CORRECTION = "nfeed_ho_correction"
_HELD_TRAIN = tuple(f"nfeed_ho_train_{index}" for index in range(MIN_SAMPLE_SIZE))
_HELD_LABELS = {item_id: 2 for item_id in _HELD_RELEVANT} | {item_id: 0 for item_id in _HELD_NOISE}


def _user_id(database: Database) -> str:
    with database.connect() as connection:
        user = connection.execute("SELECT id FROM users ORDER BY created_at DESC LIMIT 1").fetchone()
        assert user is not None
        return user["id"]


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


def _seed_same_candidate_set(
    database: Database,
    user_id: str,
    *,
    prefix: str = "nfeed",
) -> None:
    with database.connect() as connection:
        for index in range(MIN_SAMPLE_SIZE):
            _insert_item(
                connection,
                user_id=user_id,
                item_id=f"{prefix}_train_{index}",
                event_id=f"ev_{prefix}_train_{index}",
                source_type="github_release",
                updated_at=f"2026-08-20T00:0{index}:00Z",
            )
        _insert_item(
            connection,
            user_id=user_id,
            item_id=f"{prefix}_held_release",
            event_id=f"ev_{prefix}_held_release",
            source_type="github_release",
            updated_at="2026-08-21T00:00:00Z",
        )
        _insert_item(
            connection,
            user_id=user_id,
            item_id=f"{prefix}_held_rss",
            event_id=f"ev_{prefix}_held_rss",
            source_type="rss_atom",
            updated_at="2026-08-22T00:00:00Z",
            delta_type="new_fact",
        )


def _new_session(
    client: TestClient,
    database: Database,
    *,
    github_user_id: int,
    login: str,
) -> tuple[str, dict[str, str]]:
    response = client.post("/v1/sessions")
    assert response.status_code == 200
    body = response.json()
    user_id = body["userId"]
    settings = get_settings()
    cipher = TokenCipher(settings.token_encryption_key.get_secret_value())
    now = int(time.time())
    with database.connect() as connection:
        connection.execute(
            """
            INSERT OR IGNORE INTO github_connections (
                github_user_id, login, github_token_encrypted, updated_at
            ) VALUES (?, ?, ?, ?)
            """,
            (github_user_id, login, cipher.encrypt("ghp_test_token"), now),
        )
        connection.execute(
            "UPDATE users SET github_connected = 1, github_user_id = ?, github_login = ? WHERE id = ?",
            (github_user_id, login, user_id),
        )
    return user_id, {"Authorization": f"Bearer {body['accessToken']}"}


def _feed_ids(client: TestClient, auth_headers: dict[str, str]) -> list[str]:
    response = client.get("/v1/feed", headers=auth_headers, params={"limit": 50})
    assert response.status_code == 200
    return [item["id"] for item in response.json()["items"]]


def _dcg(gains: list[int]) -> float:
    total = 0.0
    for index, relevance in enumerate(gains, start=1):
        total += (math.pow(2, relevance) - 1.0) / math.log2(index + 1)
    return total


def _ndcg(gains: list[int], ideal: list[int]) -> float:
    idcg = _dcg(ideal)
    if idcg == 0:
        return 1.0
    return _dcg(gains) / idcg


def _heldout_metrics(feed_ids: list[str], *, k: int = _HELD_K) -> tuple[float, float, float]:
    ranking = [item_id for item_id in feed_ids if item_id in _HELD_LABELS]
    assert set(ranking) == set(_HELD_LABELS), ranking
    top = ranking[:k]
    precision = sum(1 for item_id in top if _HELD_LABELS[item_id] > 0) / k
    gains = [_HELD_LABELS[item_id] for item_id in top]
    ideal = sorted(_HELD_LABELS.values(), reverse=True)[:k]
    irrelevant_rate = sum(1 for item_id in top if _HELD_LABELS[item_id] == 0) / k
    return precision, _ndcg(gains, ideal), irrelevant_rate


def _seed_heldout_metric_set(database: Database, user_id: str) -> None:
    with database.connect() as connection:
        for index, item_id in enumerate(_HELD_TRAIN):
            _insert_item(
                connection,
                user_id=user_id,
                item_id=item_id,
                event_id=f"ev_{item_id}",
                source_type="github_release",
                updated_at=f"2026-08-10T00:0{index}:00Z",
            )
        for index, item_id in enumerate(_HELD_RELEVANT):
            _insert_item(
                connection,
                user_id=user_id,
                item_id=item_id,
                event_id=f"ev_{item_id}",
                source_type="github_release",
                updated_at=f"2026-08-11T00:0{index}:00Z",
            )
        for index, item_id in enumerate(_HELD_NOISE):
            _insert_item(
                connection,
                user_id=user_id,
                item_id=item_id,
                event_id=f"ev_{item_id}",
                source_type="rss_atom",
                updated_at=f"2026-08-22T00:0{index}:00Z",
                delta_type="new_fact",
            )
        _insert_item(
            connection,
            user_id=user_id,
            item_id=_HELD_UNKNOWN,
            event_id=f"ev_{_HELD_UNKNOWN}",
            source_type="github_release",
            updated_at="2026-08-12T00:00:00Z",
        )
        _insert_item(
            connection,
            user_id=user_id,
            item_id=_HELD_CORRECTION,
            event_id=f"ev_{_HELD_CORRECTION}",
            source_type="rss_atom",
            updated_at="2026-08-23T00:00:00Z",
            delta_type="correction",
        )


def test_one_important_mark_does_not_reorder_next_feed(
    client: TestClient,
    auth_headers: dict[str, str],
    database: Database,
) -> None:
    user_id = _user_id(database)
    _seed_same_candidate_set(database, user_id)
    before = _feed_ids(client, auth_headers)
    assert before.index("nfeed_held_rss") < before.index("nfeed_held_release")

    with database.connect() as connection:
        ledger_before = ledger_world_state(connection)

    marked = client.post(
        "/v1/feed/items/nfeed_train_0/feedback",
        headers=auth_headers,
        json={"type": "important"},
    )
    assert marked.status_code == 200
    after = _feed_ids(client, auth_headers)
    assert after.index("nfeed_held_rss") < after.index("nfeed_held_release")
    assert "nfeed_held_release" in after
    assert "nfeed_held_rss" in after

    with database.connect() as connection:
        assert_feedback_does_not_mutate_ledger(ledger_before, ledger_world_state(connection))
        held = connection.execute(
            "SELECT importance_reason FROM feed_items WHERE id = ?",
            ("nfeed_held_release",),
        ).fetchone()
        assert PERSONALIZATION_VERSION not in held["importance_reason"]


def test_enough_important_feedback_lifts_held_out_siblings_on_next_feed(
    client: TestClient,
    auth_headers: dict[str, str],
    database: Database,
) -> None:
    user_id = _user_id(database)
    _seed_same_candidate_set(database, user_id)
    before = _feed_ids(client, auth_headers)
    assert before.index("nfeed_held_rss") < before.index("nfeed_held_release")

    with database.connect() as connection:
        ledger_before = ledger_world_state(connection)

    for index in range(MIN_SAMPLE_SIZE):
        response = client.post(
            f"/v1/feed/items/nfeed_train_{index}/feedback",
            headers=auth_headers,
            json={"type": "important"},
        )
        assert response.status_code == 200

    after_body = client.get("/v1/feed", headers=auth_headers, params={"limit": 50})
    assert after_body.status_code == 200
    after_items = {item["id"]: item for item in after_body.json()["items"]}
    after = [item["id"] for item in after_body.json()["items"]]
    assert after.index("nfeed_held_release") < after.index("nfeed_held_rss")
    assert set(before) == set(after)
    boosted_reason = after_items["nfeed_held_release"]["displayReason"]
    untouched_reason = after_items["nfeed_held_rss"]["displayReason"]
    assert "personalization.feedback_boost" in boosted_reason["codes"]
    assert "重要マーク" in boosted_reason["text"]
    assert PERSONALIZATION_VERSION not in boosted_reason["text"]
    assert "personalization.feedback_boost" not in boosted_reason["text"]
    assert "personalization.feedback_boost" not in untouched_reason["codes"]
    assert "重要マーク" not in untouched_reason["text"]

    with database.connect() as connection:
        assert_feedback_does_not_mutate_ledger(ledger_before, ledger_world_state(connection))
        held = connection.execute(
            "SELECT importance_level, importance_reason FROM feed_items WHERE id = ?",
            ("nfeed_held_release",),
        ).fetchone()
        rss = connection.execute(
            "SELECT importance_level, importance_reason FROM feed_items WHERE id = ?",
            ("nfeed_held_rss",),
        ).fetchone()
    assert held["importance_level"] == "high"
    assert PERSONALIZATION_VERSION in held["importance_reason"]
    assert rss["importance_level"] == "medium"
    assert PERSONALIZATION_VERSION not in rss["importance_reason"]


def test_enough_not_relevant_feedback_explains_demote_on_next_feed(
    client: TestClient,
    auth_headers: dict[str, str],
    database: Database,
) -> None:
    user_id = _user_id(database)
    _seed_same_candidate_set(database, user_id)
    before = _feed_ids(client, auth_headers)
    assert before.index("nfeed_held_rss") < before.index("nfeed_held_release")

    with database.connect() as connection:
        ledger_before = ledger_world_state(connection)

    for index in range(MIN_SAMPLE_SIZE):
        response = client.post(
            f"/v1/feed/items/nfeed_train_{index}/feedback",
            headers=auth_headers,
            json={"type": "not_relevant"},
        )
        assert response.status_code == 200

    after_body = client.get("/v1/feed", headers=auth_headers, params={"limit": 50})
    assert after_body.status_code == 200
    after_items = {item["id"]: item for item in after_body.json()["items"]}
    after = [item["id"] for item in after_body.json()["items"]]
    assert "nfeed_held_release" in after_items
    assert "nfeed_held_rss" in after_items
    assert after.index("nfeed_held_rss") < after.index("nfeed_held_release")
    demoted_reason = after_items["nfeed_held_release"]["displayReason"]
    untouched_reason = after_items["nfeed_held_rss"]["displayReason"]
    assert "personalization.feedback_demote" in demoted_reason["codes"]
    assert "無関係マーク" in demoted_reason["text"]
    assert PERSONALIZATION_VERSION not in demoted_reason["text"]
    assert "personalization.feedback_demote" not in demoted_reason["text"]
    assert "personalization.feedback_demote" not in untouched_reason["codes"]
    assert "無関係マーク" not in untouched_reason["text"]

    with database.connect() as connection:
        assert_feedback_does_not_mutate_ledger(ledger_before, ledger_world_state(connection))
        held = connection.execute(
            "SELECT relation_reason FROM feed_items WHERE id = ?",
            ("nfeed_held_release",),
        ).fetchone()
        rss = connection.execute(
            "SELECT relation_reason FROM feed_items WHERE id = ?",
            ("nfeed_held_rss",),
        ).fetchone()
    assert PERSONALIZATION_VERSION in held["relation_reason"]
    assert PERSONALIZATION_VERSION not in rss["relation_reason"]


def test_sparse_and_history_rich_cohorts_keep_separate_next_feed_safety(
    client: TestClient,
    auth_headers: dict[str, str],
    database: Database,
) -> None:
    sparse_id = _user_id(database)
    _seed_same_candidate_set(database, sparse_id, prefix="sparse")
    rich_id, rich_headers = _new_session(client, database, github_user_id=456, login="richuser")
    _seed_same_candidate_set(database, rich_id, prefix="rich")

    sparse_before = _feed_ids(client, auth_headers)
    rich_before = _feed_ids(client, rich_headers)
    assert sparse_before.index("sparse_held_rss") < sparse_before.index("sparse_held_release")
    assert rich_before.index("rich_held_rss") < rich_before.index("rich_held_release")

    with database.connect() as connection:
        ledger_before = ledger_world_state(connection)

    sparse_mark = client.post(
        "/v1/feed/items/sparse_train_0/feedback",
        headers=auth_headers,
        json={"type": "important"},
    )
    assert sparse_mark.status_code == 200
    for index in range(MIN_SAMPLE_SIZE):
        response = client.post(
            f"/v1/feed/items/rich_train_{index}/feedback",
            headers=rich_headers,
            json={"type": "important"},
        )
        assert response.status_code == 200

    sparse_after = _feed_ids(client, auth_headers)
    rich_after = _feed_ids(client, rich_headers)
    assert sparse_after.index("sparse_held_rss") < sparse_after.index("sparse_held_release")
    assert rich_after.index("rich_held_release") < rich_after.index("rich_held_rss")
    assert set(sparse_before) == set(sparse_after)
    assert set(rich_before) == set(rich_after)

    with database.connect() as connection:
        assert_feedback_does_not_mutate_ledger(ledger_before, ledger_world_state(connection))
        sparse_held = connection.execute(
            "SELECT importance_reason FROM feed_items WHERE id = ?",
            ("sparse_held_release",),
        ).fetchone()
        rich_held = connection.execute(
            "SELECT importance_level, importance_reason FROM feed_items WHERE id = ?",
            ("rich_held_release",),
        ).fetchone()
        rich_on_sparse = connection.execute(
            "SELECT 1 FROM feed_items WHERE user_id = ? AND id LIKE 'rich_%'",
            (sparse_id,),
        ).fetchone()
    assert PERSONALIZATION_VERSION not in sparse_held["importance_reason"]
    assert rich_held["importance_level"] == "high"
    assert PERSONALIZATION_VERSION in rich_held["importance_reason"]
    assert rich_on_sparse is None


def test_undo_after_learned_ranking_restores_next_feed_order(
    client: TestClient,
    auth_headers: dict[str, str],
    database: Database,
) -> None:
    user_id = _user_id(database)
    _seed_same_candidate_set(database, user_id)
    before = _feed_ids(client, auth_headers)
    assert before.index("nfeed_held_rss") < before.index("nfeed_held_release")

    with database.connect() as connection:
        ledger_before = ledger_world_state(connection)

    for index in range(MIN_SAMPLE_SIZE):
        response = client.post(
            f"/v1/feed/items/nfeed_train_{index}/feedback",
            headers=auth_headers,
            json={"type": "important"},
        )
        assert response.status_code == 200

    learned = _feed_ids(client, auth_headers)
    assert learned.index("nfeed_held_release") < learned.index("nfeed_held_rss")

    for index in range(MIN_SAMPLE_SIZE):
        response = client.post(
            f"/v1/feed/items/nfeed_train_{index}/feedback",
            headers=auth_headers,
            json={"type": "undo"},
        )
        assert response.status_code == 200

    restored = _feed_ids(client, auth_headers)
    assert restored.index("nfeed_held_rss") < restored.index("nfeed_held_release")
    assert set(before) == set(restored)

    with database.connect() as connection:
        assert_feedback_does_not_mutate_ledger(ledger_before, ledger_world_state(connection))
        held = connection.execute(
            "SELECT importance_level, importance_reason FROM feed_items WHERE id = ?",
            ("nfeed_held_release",),
        ).fetchone()
    assert held["importance_level"] == "medium"
    assert PERSONALIZATION_VERSION not in held["importance_reason"]


def test_http_reset_after_learned_ranking_restores_next_feed_order(
    client: TestClient,
    auth_headers: dict[str, str],
    database: Database,
) -> None:
    user_id = _user_id(database)
    _seed_same_candidate_set(database, user_id)
    before = _feed_ids(client, auth_headers)
    assert before.index("nfeed_held_rss") < before.index("nfeed_held_release")

    with database.connect() as connection:
        ledger_before = ledger_world_state(connection)

    for index in range(MIN_SAMPLE_SIZE):
        response = client.post(
            f"/v1/feed/items/nfeed_train_{index}/feedback",
            headers=auth_headers,
            json={"type": "important"},
        )
        assert response.status_code == 200

    learned = _feed_ids(client, auth_headers)
    assert learned.index("nfeed_held_release") < learned.index("nfeed_held_rss")

    denied = client.post("/v1/feed/ranking/reset")
    assert denied.status_code == 401

    response = client.post("/v1/feed/ranking/reset", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["resetAt"] > 0

    restored = _feed_ids(client, auth_headers)
    assert restored.index("nfeed_held_rss") < restored.index("nfeed_held_release")
    assert set(before) == set(restored)

    with database.connect() as connection:
        assert_feedback_does_not_mutate_ledger(ledger_before, ledger_world_state(connection))
        held = connection.execute(
            "SELECT importance_level, importance_reason FROM feed_items WHERE id = ?",
            ("nfeed_held_release",),
        ).fetchone()
        remaining = connection.execute(
            """
            SELECT COUNT(*) AS n FROM feedback
            WHERE user_id = ? AND type = 'important'
            """,
            (user_id,),
        ).fetchone()
        other = connection.execute(
            "SELECT reset_at FROM user_ranking_resets WHERE user_id != ?",
            (user_id,),
        ).fetchone()
    assert held["importance_level"] == "medium"
    assert PERSONALIZATION_VERSION not in held["importance_reason"]
    assert remaining["n"] == MIN_SAMPLE_SIZE
    assert other is None


def test_concept_feedback_lifts_held_out_on_next_feed_same_source_type(
    client: TestClient,
    auth_headers: dict[str, str],
    database: Database,
) -> None:
    user_id = _user_id(database)
    with database.connect() as connection:
        for index in range(MIN_SAMPLE_SIZE):
            _insert_item(
                connection,
                user_id=user_id,
                item_id=f"nfeed_c_train_{index}",
                event_id=f"ev_nfeed_c_train_{index}",
                source_type="github_release",
                updated_at=f"2026-08-20T00:0{index}:00Z",
                title=f"React 19 train {index}",
            )
        _insert_item(
            connection,
            user_id=user_id,
            item_id="nfeed_c_react",
            event_id="ev_nfeed_c_react",
            source_type="rss_atom",
            updated_at="2026-08-21T00:00:00Z",
            title="React 19 release",
        )
        _insert_item(
            connection,
            user_id=user_id,
            item_id="nfeed_c_other",
            event_id="ev_nfeed_c_other",
            source_type="rss_atom",
            updated_at="2026-08-22T00:00:00Z",
            title="PostgreSQL 18 notes",
        )
        ledger_before = ledger_world_state(connection)

    before = _feed_ids(client, auth_headers)
    assert before.index("nfeed_c_other") < before.index("nfeed_c_react")

    for index in range(MIN_SAMPLE_SIZE):
        response = client.post(
            f"/v1/feed/items/nfeed_c_train_{index}/feedback",
            headers=auth_headers,
            json={"type": "important"},
        )
        assert response.status_code == 200

    after = _feed_ids(client, auth_headers)
    assert after.index("nfeed_c_react") < after.index("nfeed_c_other")
    assert set(before) == set(after)

    with database.connect() as connection:
        assert_feedback_does_not_mutate_ledger(ledger_before, ledger_world_state(connection))
        held = connection.execute(
            "SELECT importance_level, importance_reason FROM feed_items WHERE id = ?",
            ("nfeed_c_react",),
        ).fetchone()
        other = connection.execute(
            "SELECT importance_level, importance_reason FROM feed_items WHERE id = ?",
            ("nfeed_c_other",),
        ).fetchone()
    assert held["importance_level"] == "high"
    assert PERSONALIZATION_VERSION in held["importance_reason"]
    assert "react" in held["importance_reason"]
    assert other["importance_level"] == "medium"
    assert PERSONALIZATION_VERSION not in other["importance_reason"]


def test_topic_feedback_lifts_held_out_on_next_feed_same_source_type(
    client: TestClient,
    auth_headers: dict[str, str],
    database: Database,
) -> None:
    user_id = _user_id(database)
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO topics (id, user_id, name, type, priority, sort_order, created_at)
            VALUES ('topic_kotlin', ?, 'Kotlin', 'technology', 'high', 0, 0)
            """,
            (user_id,),
        )
        for index in range(MIN_SAMPLE_SIZE):
            _insert_item(
                connection,
                user_id=user_id,
                item_id=f"nfeed_t_train_{index}",
                event_id=f"ev_nfeed_t_train_{index}",
                source_type="github_release",
                updated_at=f"2026-08-20T00:0{index}:00Z",
                title=f"Kotlin 2.1 train {index}",
            )
        _insert_item(
            connection,
            user_id=user_id,
            item_id="nfeed_t_kotlin",
            event_id="ev_nfeed_t_kotlin",
            source_type="rss_atom",
            updated_at="2026-08-21T00:00:00Z",
            title="Kotlin 2.1 notes",
        )
        _insert_item(
            connection,
            user_id=user_id,
            item_id="nfeed_t_other",
            event_id="ev_nfeed_t_other",
            source_type="rss_atom",
            updated_at="2026-08-22T00:00:00Z",
            title="PostgreSQL 18 notes",
        )
        ledger_before = ledger_world_state(connection)

    before = _feed_ids(client, auth_headers)
    assert "nfeed_t_kotlin" in before and "nfeed_t_other" in before
    with database.connect() as connection:
        baseline = connection.execute(
            "SELECT importance_level FROM feed_items WHERE id = ?",
            ("nfeed_t_kotlin",),
        ).fetchone()
    assert baseline["importance_level"] == "medium"

    for index in range(MIN_SAMPLE_SIZE):
        response = client.post(
            f"/v1/feed/items/nfeed_t_train_{index}/feedback",
            headers=auth_headers,
            json={"type": "important"},
        )
        assert response.status_code == 200

    after = _feed_ids(client, auth_headers)
    assert after.index("nfeed_t_kotlin") < after.index("nfeed_t_other")
    assert set(before) == set(after)

    with database.connect() as connection:
        assert_feedback_does_not_mutate_ledger(ledger_before, ledger_world_state(connection))
        held = connection.execute(
            "SELECT importance_level, importance_reason FROM feed_items WHERE id = ?",
            ("nfeed_t_kotlin",),
        ).fetchone()
        other = connection.execute(
            "SELECT importance_level, importance_reason FROM feed_items WHERE id = ?",
            ("nfeed_t_other",),
        ).fetchone()
    assert held["importance_level"] == "high"
    assert PERSONALIZATION_VERSION in held["importance_reason"]
    assert "Kotlin" in held["importance_reason"]
    assert other["importance_level"] == "medium"
    assert PERSONALIZATION_VERSION not in other["importance_reason"]


def test_repository_feedback_lifts_held_out_on_next_feed(
    client: TestClient,
    auth_headers: dict[str, str],
    database: Database,
) -> None:
    user_id = _user_id(database)
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO github_repo_watches (
                user_id, repository_id, full_name, html_url, selected, private
            ) VALUES (?, 'repo-react', 'facebook/react', 'https://github.com/facebook/react', 1, 0)
            """,
            (user_id,),
        )
        for index, source_type in enumerate(("github_release", "github_advisory", "osv")):
            _insert_item(
                connection,
                user_id=user_id,
                item_id=f"nfeed_r_train_{index}",
                event_id=f"ev_nfeed_r_train_{index}",
                source_type=source_type,
                source_key="facebook/react",
                updated_at=f"2026-08-20T00:0{index}:00Z",
                title=f"Unrelated kitchen notes {index}",
            )
        _insert_item(
            connection,
            user_id=user_id,
            item_id="nfeed_r_react",
            event_id="ev_nfeed_r_react",
            source_type="github_release",
            source_key="facebook/react",
            updated_at="2026-08-21T00:00:00Z",
            title="Unrelated desk lamp manual",
        )
        _insert_item(
            connection,
            user_id=user_id,
            item_id="nfeed_r_go",
            event_id="ev_nfeed_r_go",
            source_type="github_release",
            source_key="golang/go",
            updated_at="2026-08-22T00:00:00Z",
            title="Unrelated garden hose specs",
        )
        ledger_before = ledger_world_state(connection)

    before = _feed_ids(client, auth_headers)
    assert "nfeed_r_react" in before and "nfeed_r_go" in before
    with database.connect() as connection:
        baseline = connection.execute(
            "SELECT importance_level FROM feed_items WHERE id = ?",
            ("nfeed_r_react",),
        ).fetchone()
    assert baseline["importance_level"] == "medium"

    for index in range(MIN_SAMPLE_SIZE):
        response = client.post(
            f"/v1/feed/items/nfeed_r_train_{index}/feedback",
            headers=auth_headers,
            json={"type": "important"},
        )
        assert response.status_code == 200

    after = _feed_ids(client, auth_headers)
    assert after.index("nfeed_r_react") < after.index("nfeed_r_go")
    assert set(before) == set(after)

    with database.connect() as connection:
        assert_feedback_does_not_mutate_ledger(ledger_before, ledger_world_state(connection))
        held = connection.execute(
            "SELECT importance_level, importance_reason FROM feed_items WHERE id = ?",
            ("nfeed_r_react",),
        ).fetchone()
        other = connection.execute(
            "SELECT importance_level, importance_reason FROM feed_items WHERE id = ?",
            ("nfeed_r_go",),
        ).fetchone()
    assert held["importance_level"] == "high"
    assert PERSONALIZATION_VERSION in held["importance_reason"]
    assert "facebook/react" in held["importance_reason"]
    assert other["importance_level"] == "medium"
    assert PERSONALIZATION_VERSION not in other["importance_reason"]


def test_impact_feedback_lifts_held_out_on_next_feed(
    client: TestClient,
    auth_headers: dict[str, str],
    database: Database,
) -> None:
    user_id = _user_id(database)
    with database.connect() as connection:
        for index, source_type in enumerate(("rss_atom", "github_release", "package_registry")):
            _insert_item(
                connection,
                user_id=user_id,
                item_id=f"nfeed_i_train_{index}",
                event_id=f"ev_nfeed_i_train_{index}",
                source_type=source_type,
                updated_at=f"2026-08-20T00:0{index}:00Z",
                delta_type="state_update",
                title=f"Unrelated kitchen notes {index}",
            )
        _insert_item(
            connection,
            user_id=user_id,
            item_id="nfeed_i_state",
            event_id="ev_nfeed_i_state",
            source_type="rss_atom",
            updated_at="2026-08-21T00:00:00Z",
            delta_type="state_update",
            title="Unrelated desk lamp manual",
        )
        _insert_item(
            connection,
            user_id=user_id,
            item_id="nfeed_i_other",
            event_id="ev_nfeed_i_other",
            source_type="rss_atom",
            updated_at="2026-08-22T00:00:00Z",
            title="Unrelated garden hose specs",
        )
        ledger_before = ledger_world_state(connection)

    before = _feed_ids(client, auth_headers)
    assert "nfeed_i_state" in before and "nfeed_i_other" in before
    with database.connect() as connection:
        baseline = connection.execute(
            "SELECT importance_level FROM feed_items WHERE id = ?",
            ("nfeed_i_state",),
        ).fetchone()
    assert baseline["importance_level"] == "medium"

    for index in range(MIN_SAMPLE_SIZE):
        response = client.post(
            f"/v1/feed/items/nfeed_i_train_{index}/feedback",
            headers=auth_headers,
            json={"type": "important"},
        )
        assert response.status_code == 200

    after = _feed_ids(client, auth_headers)
    assert after.index("nfeed_i_state") < after.index("nfeed_i_other")
    assert set(before) == set(after)

    with database.connect() as connection:
        assert_feedback_does_not_mutate_ledger(ledger_before, ledger_world_state(connection))
        held = connection.execute(
            "SELECT importance_level, importance_reason FROM feed_items WHERE id = ?",
            ("nfeed_i_state",),
        ).fetchone()
        other = connection.execute(
            "SELECT importance_level, importance_reason FROM feed_items WHERE id = ?",
            ("nfeed_i_other",),
        ).fetchone()
    assert held["importance_level"] == "high"
    assert PERSONALIZATION_VERSION in held["importance_reason"]
    assert "state_update" in held["importance_reason"]
    assert other["importance_level"] == "medium"
    assert PERSONALIZATION_VERSION not in other["importance_reason"]


def test_feedback_ranking_does_not_drop_correction_from_next_feed(
    client: TestClient,
    auth_headers: dict[str, str],
    database: Database,
) -> None:
    user_id = _user_id(database)
    _seed_same_candidate_set(database, user_id)
    with database.connect() as connection:
        _insert_item(
            connection,
            user_id=user_id,
            item_id="nfeed_correction",
            event_id="ev_nfeed_correction",
            source_type="rss_atom",
            updated_at="2026-08-23T00:00:00Z",
            delta_type="correction",
        )
        ledger_before = ledger_world_state(connection)

    before = _feed_ids(client, auth_headers)
    assert "nfeed_correction" in before

    for index in range(MIN_SAMPLE_SIZE):
        response = client.post(
            f"/v1/feed/items/nfeed_train_{index}/feedback",
            headers=auth_headers,
            json={"type": "important"},
        )
        assert response.status_code == 200

    after = _feed_ids(client, auth_headers)
    assert "nfeed_correction" in after
    assert set(before) == set(after)

    with database.connect() as connection:
        assert_feedback_does_not_mutate_ledger(ledger_before, ledger_world_state(connection))
        row = connection.execute(
            "SELECT status, dismissed FROM feed_items WHERE id = ?",
            ("nfeed_correction",),
        ).fetchone()
    assert row["status"] == "unread"
    assert int(row["dismissed"]) == 0


def test_heldout_precision_ndcg_and_irrelevant_rate_improve_on_next_feed(
    client: TestClient,
    auth_headers: dict[str, str],
    database: Database,
) -> None:
    user_id = _user_id(database)
    _seed_heldout_metric_set(database, user_id)
    unknown_ids = {*_HELD_RELEVANT, *_HELD_NOISE, _HELD_UNKNOWN, _HELD_CORRECTION}

    with database.connect() as connection:
        ledger_before = ledger_world_state(connection)

    before_ids = _feed_ids(client, auth_headers)
    assert unknown_ids <= set(before_ids)
    before_p, before_ndcg, before_irrelevant = _heldout_metrics(before_ids)
    assert before_p < 1.0
    assert before_irrelevant > 0.0

    for item_id in _HELD_TRAIN:
        response = client.post(
            f"/v1/feed/items/{item_id}/feedback",
            headers=auth_headers,
            json={"type": "important"},
        )
        assert response.status_code == 200

    after_ids = _feed_ids(client, auth_headers)
    assert unknown_ids <= set(after_ids)
    assert set(before_ids) == set(after_ids)
    after_p, after_ndcg, after_irrelevant = _heldout_metrics(after_ids)

    assert after_p >= before_p
    assert after_ndcg >= before_ndcg
    assert after_irrelevant <= before_irrelevant
    assert after_p > before_p or after_irrelevant < before_irrelevant
    assert after_p >= 0.6
    assert after_irrelevant <= 0.4

    hidden_unknown = unknown_ids - set(after_ids)
    assert not hidden_unknown

    with database.connect() as connection:
        assert_feedback_does_not_mutate_ledger(ledger_before, ledger_world_state(connection))
        row = connection.execute(
            "SELECT status, dismissed FROM feed_items WHERE id = ?",
            (_HELD_CORRECTION,),
        ).fetchone()
        event_ids = [
            item["event_id"]
            for item in connection.execute(
                "SELECT id, event_id FROM feed_items WHERE user_id = ?",
                (user_id,),
            ).fetchall()
            if item["id"] in unknown_ids
        ]
    assert row["status"] == "unread"
    assert int(row["dismissed"]) == 0
    assert len(event_ids) == len(set(event_ids))
