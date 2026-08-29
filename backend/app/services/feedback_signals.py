from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Final

FAMILY_RANKING = "ranking"
FAMILY_KNOWLEDGE = "knowledge"
FAMILY_FOLLOW = "follow"
FAMILY_PREFERENCE = "preference"

ALLOWED_FEEDBACK_TYPES: Final[frozenset[str]] = frozenset(
    {
        "important",
        "not_relevant",
        "follow",
        "already_knew",
        "learned_now",
        "less_like_this",
        "undo",
    }
)

FAMILY_BY_TYPE: Final[dict[str, str]] = {
    "important": FAMILY_RANKING,
    "not_relevant": FAMILY_RANKING,
    "already_knew": FAMILY_KNOWLEDGE,
    "learned_now": FAMILY_KNOWLEDGE,
    "follow": FAMILY_FOLLOW,
    "less_like_this": FAMILY_PREFERENCE,
}

TYPES_BY_FAMILY: Final[dict[str, frozenset[str]]] = {
    FAMILY_RANKING: frozenset({"important", "not_relevant"}),
    FAMILY_KNOWLEDGE: frozenset({"already_knew", "learned_now"}),
    FAMILY_FOLLOW: frozenset({"follow"}),
    FAMILY_PREFERENCE: frozenset({"less_like_this"}),
}

RANKING_FEATURE_TYPES: Final[tuple[str, ...]] = (
    "important",
    "not_relevant",
    "follow",
    "already_knew",
    "learned_now",
    "less_like_this",
)

# Canonical Event / Claim / Delta world state. User tables (feedback,
# event_follows, user_knowledge_signals, feed_items flags, exposures) are excluded.
_LEDGER_ROW_QUERIES: Final[dict[str, str]] = {
    "events": "SELECT * FROM events ORDER BY id",
    "deltas": "SELECT * FROM deltas ORDER BY id",
    "observations": "SELECT * FROM observations ORDER BY id",
    "ledger_events": "SELECT * FROM ledger_events ORDER BY id",
    "state_claims": "SELECT * FROM state_claims ORDER BY id",
    "claim_relations": "SELECT * FROM claim_relations ORDER BY id",
    "claim_evidence": "SELECT * FROM claim_evidence ORDER BY id",
    "delta_claim_map": "SELECT * FROM delta_claim_map ORDER BY delta_id",
    "event_source_claim_map": "SELECT * FROM event_source_claim_map ORDER BY source_id",
}

LEDGER_TABLES: Final[tuple[str, ...]] = tuple(_LEDGER_ROW_QUERIES)


def is_allowed_feedback_type(feedback_type: str) -> bool:
    return feedback_type in ALLOWED_FEEDBACK_TYPES


def family_for_type(feedback_type: str) -> str | None:
    return FAMILY_BY_TYPE.get(feedback_type)


def types_for_family(family: str) -> frozenset[str]:
    return TYPES_BY_FAMILY.get(family, frozenset())


def resolve_write_family(*, feedback_type: str, latest_family: str | None) -> str | None:
    """Family written on the new ledger row.

    `undo` inherits the latest non-undo family for that (user, feed_item).
    Latest-state queries then treat `undo` as clearing that family.
    """
    if feedback_type == "undo":
        return latest_family
    return family_for_type(feedback_type)


def latest_family_for_item(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    feed_item_id: str,
) -> str | None:
    row = connection.execute(
        """
        SELECT COALESCE(
            family,
            CASE type
                WHEN 'important' THEN 'ranking'
                WHEN 'not_relevant' THEN 'ranking'
                WHEN 'already_knew' THEN 'knowledge'
                WHEN 'learned_now' THEN 'knowledge'
                WHEN 'follow' THEN 'follow'
                WHEN 'less_like_this' THEN 'preference'
                ELSE NULL
            END
        ) AS family
        FROM feedback
        WHERE user_id = ? AND feed_item_id = ? AND type != 'undo'
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (user_id, feed_item_id),
    ).fetchone()
    if row is None:
        return None
    family = row["family"]
    return str(family) if family is not None else None


def latest_type_for_family(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    feed_item_id: str,
    family: str,
) -> str | None:
    """Latest row wins per (user, feed_item, type-family). `undo` is a real latest type."""
    family_types = types_for_family(family)
    if not family_types:
        return None
    placeholders = ", ".join("?" for _ in family_types)
    row = connection.execute(
        f"""
        SELECT type
        FROM feedback
        WHERE user_id = ? AND feed_item_id = ?
          AND (
              family = ?
              OR (family IS NULL AND type IN ({placeholders}))
              OR (type = 'undo' AND family = ?)
          )
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,  # nosec B608
        (user_id, feed_item_id, family, *sorted(family_types), family),
    ).fetchone()
    if row is None:
        return None
    return str(row["type"])


def ledger_world_state(connection: sqlite3.Connection) -> dict[str, object]:
    """Hash + count of canonical Event/Claim/Delta tables."""
    counts: dict[str, int] = {}
    hashes: dict[str, str] = {}
    for table, query in _LEDGER_ROW_QUERIES.items():
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        if exists is None:
            counts[table] = 0
            hashes[table] = ""
            continue
        rows = list(connection.execute(query).fetchall())
        counts[table] = len(rows)
        payload = json.dumps([tuple(row) for row in rows], default=str, separators=(",", ":"))
        hashes[table] = hashlib.sha256(payload.encode()).hexdigest()
    return {"counts": counts, "hashes": hashes}


def assert_feedback_does_not_mutate_ledger(
    before: dict[str, object],
    after: dict[str, object],
) -> None:
    if before != after:
        raise AssertionError(
            "typed feedback must not mutate canonical Event/Claim/Delta world state: "
            f"before={before!r} after={after!r}"
        )
