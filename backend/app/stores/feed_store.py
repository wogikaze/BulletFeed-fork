from __future__ import annotations

import json
import secrets
import sqlite3
import time
from datetime import UTC, datetime

from app.database import Database
from app.db.knownness import (
    KNOWNNESS_DELIVERED,
    KNOWNNESS_DISPLAYED,
    KNOWNNESS_READ,
    UNDISPLAYED_DELIVERY_RETRY_LIMIT,
)
from app.errors import not_found, unprocessable
from app.schemas.common import Delta, Importance, MatchedRepository, Relation, SourceEvidence
from app.schemas.feed import PublicFeedItem
from app.services.cross_source_suppress import SourceCandidate, project_candidates
from app.services.display_reason import DisplayReasonInputs, build_display_reason
from app.services.feedback_signals import (
    FAMILY_FOLLOW,
    FAMILY_KNOWLEDGE,
    FAMILY_PREFERENCE,
    FAMILY_RANKING,
    is_allowed_feedback_type,
    latest_family_for_item,
    resolve_write_family,
    types_for_family,
)
from app.services.follow_baseline import SUBJECT_EVENT, record_follow_baseline
from app.services.impact_features import (
    build_impact_record,
    parse_observation_payload,
    ranking_impact_snapshot,
)
from app.services.knowledge_evidence import (
    CONFIDENCE_NONE,
    KIND_ALREADY_KNEW,
    KIND_DELIVERED,
    KIND_DISPLAYED,
    KIND_LEARNED_NOW,
    KIND_READ,
    STATE_UNKNOWN,
    append_knowledge_evidence,
    derive_knowledge_state,
    list_knowledge_evidence,
)
from app.services.knowledge_identity import (
    replay_knowledge_state_for_identity,
    resolve_claim_knowledge_id,
    resolve_claim_knowledge_ids,
)
from app.services.multiobjective_ranker import (
    RANKING_POLICY_VERSION,
    RankerCandidate,
    decode_ranking_cursor,
    paginate_ranked,
    rank_candidates,
)
from app.services.ranking_feedback import apply_feedback_ranking
from app.services.relation import RELATION_FEATURE_VERSION, evaluate_relation
from app.services.session_telemetry import (
    KIND_CARD_DISPLAYED,
    KIND_DETAIL_READ,
    KIND_FEEDBACK,
    KIND_FOLLOW,
    record_session_outcome,
)
from app.services.viewport_exposure import (
    POLICY_VERSION,
    is_meaningful_display,
)

_VALID_RELATIONS = {"direct", "adjacent", "reference"}
_VALID_STATUSES = {"unread", "read"}


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _decode_cursor(cursor: str) -> str:
    try:
        return decode_ranking_cursor(cursor, policy_version=RANKING_POLICY_VERSION)
    except ValueError as exc:
        raise unprocessable("cursor is invalid or from an obsolete ranking version") from exc


def _knownness_by_feed_item(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    rows: list[sqlite3.Row],
    identity_map: dict | None = None,
) -> dict[str, tuple[str, str]]:
    evidence = list_knowledge_evidence(connection, user_id=user_id)
    by_claim: dict[str, list] = {}
    for row in evidence:
        if row.claim_id:
            by_claim.setdefault(row.claim_id, []).append(row)
    states: dict[str, tuple[str, str]] = {}
    mapped_by_claim = identity_map
    if mapped_by_claim is None:
        mapped_by_claim = resolve_claim_knowledge_ids(
            connection,
            [row["claim_id"] for row in rows if row["claim_id"]],
        )
    for feed_row in rows:
        claim_id = feed_row["claim_id"]
        if not claim_id:
            states[feed_row["id"]] = (STATE_UNKNOWN, CONFIDENCE_NONE)
            continue
        mapped = mapped_by_claim.get(claim_id)
        if mapped is not None and mapped.decision in {"equivalent", "singleton"}:
            derived = replay_knowledge_state_for_identity(
                connection,
                user_id=user_id,
                knowledge_id=mapped.knowledge_id,
                now=int(time.time()),
            )
        else:
            derived = derive_knowledge_state(by_claim.get(claim_id, ()), now=int(time.time()))
        states[feed_row["id"]] = (derived.state, derived.confidence)
    return states


def _revision_class_from_delta(delta_type: str | None) -> str:
    normalized = (delta_type or "").strip().casefold()
    if normalized == "correction":
        return "CORRECTION"
    if normalized in {"unresolved_conflict", "conflict", "unresolved_contradiction"}:
        return "UNRESOLVED_CONTRADICTION"
    if normalized == "detail":
        return "DETAIL"
    if normalized == "state_update":
        return "STATE_UPDATE"
    return ""


def _dependence_key(*, source_type: str, source_key: str, title: str) -> str:
    token = (source_key or title or "").strip()
    upper = token.upper()
    if source_type in {"github_advisory", "osv"} or upper.startswith(("GHSA-", "OSV-")):
        return f"advisory:{upper}"
    if source_type and source_key:
        return f"{source_type}:{source_key.casefold()}"
    return f"candidate:{source_type}:{token.casefold()}"


def _source_kind(raw: str) -> str:
    kind = (raw or "").strip()
    if kind in {
        "statuspage",
        "github_advisory",
        "osv",
        "github_release",
        "github_sbom",
        "rss_atom",
        "json_feed",
        "official_changelog",
        "documentation",
    }:
        return kind
    return "documentation"


def _first_sources_by_event(
    connection: sqlite3.Connection,
    event_ids: list[str],
) -> dict[str, sqlite3.Row]:
    if not event_ids:
        return {}
    placeholders = ",".join("?" for _ in event_ids)
    rows = connection.execute(
        f"""
        SELECT event_id, publisher, kind, title, url, published_at, retrieved_at, evidence
        FROM event_sources
        WHERE event_id IN ({placeholders})
        ORDER BY published_at, id
        """,  # nosec B608
        event_ids,
    ).fetchall()
    first: dict[str, sqlite3.Row] = {}
    for row in rows:
        first.setdefault(row["event_id"], row)
    return first


def _source_candidate_from_feed_row(
    row: sqlite3.Row,
    *,
    knownness: tuple[str, str],
    identity_label: str,
    identity_confidence: str,
    source: sqlite3.Row | None,
) -> SourceCandidate:
    keys = set(row.keys())
    source_type = row["source_type"] if "source_type" in keys else "unknown"
    source_key = row["source_key"] if "source_key" in keys else ""
    value = row["claim_value"] if "claim_value" in keys else ""
    detail = row["claim_detail"] if "claim_detail" in keys else ""
    slot = row["claim_slot"] if "claim_slot" in keys else ""
    publisher = source["publisher"] if source is not None else (source_key or source_type)
    kind = _source_kind(source["kind"] if source is not None else source_type)
    title = source["title"] if source is not None else row["title"]
    url = source["url"] if source is not None else ""
    published_at = source["published_at"] if source is not None else row["updated_at"]
    retrieved_at = source["retrieved_at"] if source is not None else row["updated_at"]
    evidence = source["evidence"] if source is not None else (detail or row["title"])
    return SourceCandidate(
        candidate_id=row["id"],
        source_id=f"{source_type}:{source_key}" if source_key else row["id"],
        publisher=publisher,
        kind=kind,
        title=title,
        url=url,
        published_at=published_at,
        retrieved_at=retrieved_at,
        evidence=evidence,
        value=value or "",
        detail=detail or "",
        slot=slot or "",
        revision_class=_revision_class_from_delta(row["delta_type"]) or None,
        dependence_key=_dependence_key(
            source_type=source_type,
            source_key=source_key,
            title=title,
        ),
        knowledge_state=knownness[0],
        knowledge_confidence=knownness[1],
        importance_level=row["importance_level"],
        identity_label=identity_label,
        identity_confidence=identity_confidence,
        event_id=str(row["event_id"]) if "event_id" in keys and row["event_id"] else None,
    )


def _identity_for_claim(
    connection: sqlite3.Connection,
    claim_id: str | None,
    identity_map: dict | None = None,
) -> tuple[str, str]:
    if not claim_id:
        return "uncertain", "none"
    mapped = (
        identity_map.get(claim_id)
        if identity_map is not None
        else resolve_claim_knowledge_id(connection, claim_id)
    )
    if mapped is None:
        return "uncertain", "none"
    if mapped.decision == "equivalent":
        return "same_target", mapped.confidence
    return "uncertain", mapped.confidence or "none"


def _relation_score_from_feed_row(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    row: sqlite3.Row,
) -> float:
    keys = set(row.keys())
    stored_version = row["relation_feature_version"] if "relation_feature_version" in keys else ""
    if stored_version == RELATION_FEATURE_VERSION:
        return max(0.0, min(1.0, float(row["relation_score"] or 0.0)))
    signal = evaluate_relation(
        connection,
        user_id=user_id,
        source_type=row["source_type"],
        source_key=row["source_key"],
        event_title=row["title"],
        event_summary=row["event_summary"] or row["delta_summary"],
    )
    return signal.score


def _candidate_from_feed_row(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    row: sqlite3.Row,
    knownness: tuple[str, str],
    identity_map: dict | None = None,
) -> RankerCandidate:
    topics = json.loads(row["matched_topics_json"] or "[]")
    topic_key = topics[0] if topics else row["event_id"]
    keys = set(row.keys())
    record = build_impact_record(
        source_type=row["source_type"],
        source_key=row["source_key"],
        delta_type=row["delta_type"],
        title=row["title"],
        summary=row["event_summary"] or row["delta_summary"],
        payload=parse_observation_payload(
            row["observation_payload"] if "observation_payload" in keys else None
        ),
        claim_value=row["claim_value"] if "claim_value" in keys else "",
        claim_detail=row["claim_detail"] if "claim_detail" in keys else "",
    )
    snapshot = ranking_impact_snapshot(record)
    identity_label, identity_confidence = _identity_for_claim(
        connection,
        row["claim_id"],
        identity_map=identity_map,
    )
    return RankerCandidate(
        item_id=row["id"],
        event_id=row["event_id"],
        redundancy_group=row["event_id"],
        topic_key=topic_key,
        relation_level=row["relation_level"],
        relation_score=_relation_score_from_feed_row(connection, user_id=user_id, row=row),
        personalization_rank=int(row["personalization_rank"] or 0),
        importance_level=row["importance_level"],
        impact_snapshot=snapshot,
        knownness_state=knownness[0],
        knownness_confidence=knownness[1],
        delta_type=row["delta_type"],
        source_type=row["source_type"],
        updated_at=row["updated_at"],
        identity_label=identity_label,
        identity_confidence=identity_confidence,
        revision_class=_revision_class_from_delta(row["delta_type"]),
    )


def _row_to_item(
    row: sqlite3.Row,
    delivery_id: str,
    following: bool,
    sources: list[SourceEvidence],
    additional_sources: list[SourceEvidence] | None = None,
    *,
    display_inputs: DisplayReasonInputs | None = None,
) -> PublicFeedItem:
    matched_repos = [
        MatchedRepository.model_validate(item) for item in json.loads(row["matched_repos_json"])
    ]
    matched_topics = json.loads(row["matched_topics_json"])
    extras = list(additional_sources or [])
    reason_inputs = display_inputs or DisplayReasonInputs(
        ranking_policy_version=RANKING_POLICY_VERSION,
        priority_rule=None,
        redundancy_penalty=0.0,
        relation_level=row["relation_level"],
        relation_reason=row["relation_reason"],
        matched_topics=tuple(matched_topics),
        matched_repository_names=tuple(item.name for item in matched_repos),
        importance_level=row["importance_level"],
        delta_type=row["delta_type"],
        knownness_state=STATE_UNKNOWN,
        knownness_confidence=CONFIDENCE_NONE,
        additional_source_roles=tuple(item.role for item in extras if item.role),
    )
    return PublicFeedItem(
        id=row["id"],
        event_id=row["event_id"],
        delta=Delta(
            id=row["delta_id"],
            type=row["delta_type"],
            summary=row["delta_summary"],
            before=row["before_text"],
            after=row["after_text"],
            occurred_at=row["occurred_at"],
        ),
        title=row["title"],
        importance=Importance(
            level=row["importance_level"],
            reason=row["importance_reason"],
            confidence=row["importance_confidence"],
        ),
        relation=Relation(
            level=row["relation_level"],
            reason=row["relation_reason"],
            matched_topics=matched_topics,
            matched_repositories=matched_repos,
        ),
        status=row["status"],
        following=following,
        updated_at=row["updated_at"],
        delivery_id=delivery_id,
        sources=sources,
        additional_sources=extras,
        display_reason=build_display_reason(reason_inputs),
    )


def _upsert_delivered(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    claim_id: str,
    delivery_id: str,
    delivered_at: str,
    event_id: str | None = None,
    delta_id: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO user_claim_exposures (
            user_id, claim_id, delivery_id, delivered_at, state,
            displayed_at, read_at, delivery_count
        ) VALUES (?, ?, ?, ?, ?, NULL, NULL, 1)
        ON CONFLICT(user_id, claim_id) DO UPDATE SET
            delivery_id = CASE
                WHEN user_claim_exposures.state = 'delivered'
                THEN excluded.delivery_id
                ELSE user_claim_exposures.delivery_id
            END,
            delivered_at = CASE
                WHEN user_claim_exposures.state = 'delivered'
                THEN excluded.delivered_at
                ELSE user_claim_exposures.delivered_at
            END,
            delivery_count = CASE
                WHEN user_claim_exposures.state = 'delivered'
                THEN user_claim_exposures.delivery_count + 1
                ELSE user_claim_exposures.delivery_count
            END
        """,
        (user_id, claim_id, delivery_id, delivered_at, KNOWNNESS_DELIVERED),
    )
    append_knowledge_evidence(
        connection,
        user_id=user_id,
        kind=KIND_DELIVERED,
        source_id=delivery_id,
        claim_id=claim_id,
        event_id=event_id,
        delta_id=delta_id,
    )


def _upsert_displayed(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    claim_id: str,
    delivery_id: str,
    displayed_at: str,
    event_id: str | None = None,
    delta_id: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO user_claim_exposures (
            user_id, claim_id, delivery_id, delivered_at, state,
            displayed_at, read_at, delivery_count
        ) VALUES (?, ?, ?, ?, ?, ?, NULL, 1)
        ON CONFLICT(user_id, claim_id) DO UPDATE SET
            state = CASE
                WHEN user_claim_exposures.state = 'read' THEN 'read'
                ELSE 'displayed'
            END,
            displayed_at = COALESCE(user_claim_exposures.displayed_at, excluded.displayed_at),
            delivery_id = CASE
                WHEN user_claim_exposures.state = 'delivered' THEN excluded.delivery_id
                ELSE user_claim_exposures.delivery_id
            END
        """,
        (
            user_id,
            claim_id,
            delivery_id,
            displayed_at,
            KNOWNNESS_DISPLAYED,
            displayed_at,
        ),
    )
    append_knowledge_evidence(
        connection,
        user_id=user_id,
        kind=KIND_DISPLAYED,
        source_id=delivery_id,
        claim_id=claim_id,
        event_id=event_id,
        delta_id=delta_id,
    )


def _record_read(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    feed_item_id: str,
) -> None:
    mapped = connection.execute(
        """
        SELECT m.claim_id, f.event_id, f.delta_id
        FROM feed_items f
        JOIN delta_claim_map m ON m.delta_id = f.delta_id
        WHERE f.id = ? AND f.user_id = ?
        """,
        (feed_item_id, user_id),
    ).fetchone()
    if mapped is None:
        return
    delivery = connection.execute(
        """
        SELECT id, created_at
        FROM deliveries
        WHERE feed_item_id = ? AND user_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (feed_item_id, user_id),
    ).fetchone()
    now = _now_iso()
    if delivery is None:
        delivery_id = f"dlv_{secrets.token_urlsafe(10)}"
        connection.execute(
            "INSERT INTO deliveries (id, feed_item_id, user_id, created_at) VALUES (?, ?, ?, ?)",
            (delivery_id, feed_item_id, user_id, now),
        )
        delivered_at = now
    else:
        delivery_id = delivery["id"]
        delivered_at = delivery["created_at"]
    connection.execute(
        """
        INSERT INTO user_claim_exposures (
            user_id, claim_id, delivery_id, delivered_at, state,
            displayed_at, read_at, delivery_count
        ) VALUES (?, ?, ?, ?, ?, NULL, ?, 1)
        ON CONFLICT(user_id, claim_id) DO UPDATE SET
            state = 'read',
            read_at = COALESCE(user_claim_exposures.read_at, excluded.read_at)
        """,
        (
            user_id,
            mapped["claim_id"],
            delivery_id,
            delivered_at,
            KNOWNNESS_READ,
            now,
        ),
    )
    append_knowledge_evidence(
        connection,
        user_id=user_id,
        kind=KIND_READ,
        source_id=delivery_id,
        claim_id=mapped["claim_id"],
        event_id=mapped["event_id"],
        delta_id=mapped["delta_id"],
    )


def _next_created_at(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    feed_item_id: str,
) -> int:
    """Second-resolution clock, incremented when the same item is written again.

    Ranking reset compares `feedback.created_at > reset_at` in seconds. Latest-state
    still needs a total order, so a same-second write on the same item steps +1.
    """
    now = int(datetime.now().timestamp())
    latest = connection.execute(
        """
        SELECT MAX(created_at) AS created_at
        FROM feedback
        WHERE user_id = ? AND feed_item_id = ?
        """,
        (user_id, feed_item_id),
    ).fetchone()
    latest_at = latest["created_at"] if latest is not None else None
    if latest_at is not None and now <= int(latest_at):
        return int(latest_at) + 1
    return now


def _supersede_family(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    feed_item_id: str,
    family: str | None,
) -> None:
    if family is None:
        return
    family_types = types_for_family(family)
    placeholders = ", ".join("?" for _ in family_types) if family_types else "?"
    type_params: tuple[str, ...] = tuple(sorted(family_types)) if family_types else ("",)
    connection.execute(
        f"""
        UPDATE feedback
        SET superseded = 1
        WHERE user_id = ? AND feed_item_id = ? AND superseded = 0
          AND (
              family = ?
              OR (family IS NULL AND type IN ({placeholders}))
          )
        """,  # nosec B608
        (user_id, feed_item_id, family, *type_params),
    )


def _apply_feedback_derived_state(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    feed_item_id: str,
    event_id: str,
    delta_id: str,
    claim_id: str | None,
    feedback_type: str,
    family: str | None,
    created_at: int,
) -> None:
    if family == FAMILY_RANKING:
        if feedback_type == "not_relevant":
            connection.execute(
                """
                UPDATE feed_items
                SET dismissed = 1, status = 'read'
                WHERE id = ? AND user_id = ?
                """,
                (feed_item_id, user_id),
            )
        elif feedback_type == "important":
            connection.execute(
                """
                UPDATE feed_items
                SET marked_important = 1, dismissed = 0
                WHERE id = ? AND user_id = ?
                """,
                (feed_item_id, user_id),
            )
        elif feedback_type == "undo":
            connection.execute(
                """
                UPDATE feed_items
                SET marked_important = 0, dismissed = 0
                WHERE id = ? AND user_id = ?
                """,
                (feed_item_id, user_id),
            )
        return

    if family == FAMILY_FOLLOW:
        following = 0 if feedback_type == "undo" else 1
        previous = connection.execute(
            "SELECT following FROM event_follows WHERE user_id = ? AND event_id = ?",
            (user_id, event_id),
        ).fetchone()
        was_following = bool(previous["following"]) if previous is not None else False
        connection.execute(
            """
            INSERT INTO event_follows (user_id, event_id, following)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, event_id) DO UPDATE SET following = excluded.following
            """,
            (user_id, event_id, following),
        )
        if following and not was_following:
            record_follow_baseline(
                connection,
                user_id=user_id,
                subject_kind=SUBJECT_EVENT,
                subject_id=event_id,
            )
        return

    if family == FAMILY_KNOWLEDGE:
        connection.execute(
            """
            UPDATE user_knowledge_signals
            SET superseded = 1
            WHERE user_id = ? AND feed_item_id = ? AND superseded = 0
            """,
            (user_id, feed_item_id),
        )
        if feedback_type != "undo":
            connection.execute(
                """
                INSERT INTO user_knowledge_signals (
                    id, user_id, feed_item_id, event_id, delta_id, claim_id,
                    signal, created_at, superseded
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    f"uks_{secrets.token_urlsafe(8)}",
                    user_id,
                    feed_item_id,
                    event_id,
                    delta_id,
                    claim_id,
                    feedback_type,
                    created_at,
                ),
            )
        return

    if family == FAMILY_PREFERENCE:
        return


class FeedStore:
    def __init__(self, database: Database) -> None:
        self._database = database

    def list_feed(
        self,
        user_id: str,
        *,
        relation: str | None,
        item_status: str | None,
        cursor: str | None,
        limit: int,
    ) -> tuple[list[PublicFeedItem], str | None]:
        if relation is not None and relation not in _VALID_RELATIONS:
            raise unprocessable("relation is invalid")
        if item_status is not None and item_status not in _VALID_STATUSES:
            raise unprocessable("status is invalid")
        if limit < 1 or limit > 50:
            raise unprocessable("limit must be 1-50")

        if cursor:
            _decode_cursor(cursor)

        with self._database.connect() as connection:
            follows = {
                row["event_id"]: bool(row["following"])
                for row in connection.execute(
                    "SELECT event_id, following FROM event_follows WHERE user_id = ?",
                    (user_id,),
                )
            }

            inner_sql = """
                SELECT f.*, d.type AS delta_type, d.summary AS delta_summary,
                       d.before_text, d.after_text, d.occurred_at,
                       claim_map.claim_id AS claim_id,
                       COALESCE(le.source_type, 'unknown') AS source_type,
                       COALESCE(le.source_key, '') AS source_key,
                       COALESCE(e.summary, '') AS event_summary,
                       COALESCE(sc.value_text, '') AS claim_value,
                       COALESCE(sc.detail_text, '') AS claim_detail,
                       COALESCE(sc.slot, '') AS claim_slot,
                       obs.payload_json AS observation_payload
                FROM feed_items f
                JOIN deltas d ON d.id = f.delta_id
                LEFT JOIN events e ON e.id = f.event_id
                LEFT JOIN ledger_events le ON le.id = f.event_id
                LEFT JOIN delta_claim_map claim_map ON claim_map.delta_id = f.delta_id
                LEFT JOIN state_claims sc ON sc.id = claim_map.claim_id
                LEFT JOIN observations obs ON obs.id = sc.observation_id
                LEFT JOIN user_claim_exposures knownness
                    ON knownness.user_id = f.user_id
                   AND knownness.claim_id = claim_map.claim_id
                WHERE f.user_id = ? AND f.dismissed = 0
                  AND (
                      knownness.claim_id IS NULL
                      OR knownness.state != ?
                      OR knownness.delivery_count < ?
                  )
                  AND (
                      NOT EXISTS (
                          SELECT 1 FROM event_visibility v
                          WHERE v.event_id = f.event_id AND v.restricted = 1
                      )
                      OR EXISTS (
                          SELECT 1 FROM event_user_access a
                          WHERE a.event_id = f.event_id
                            AND a.user_id = f.user_id
                            AND a.expires_at > ?
                      )
                  )
            """
            params: list[object] = [
                user_id,
                KNOWNNESS_DELIVERED,
                UNDISPLAYED_DELIVERY_RETRY_LIMIT,
                int(datetime.now(UTC).timestamp()),
            ]
            if relation is not None:
                inner_sql += " AND f.relation_level = ?"
                params.append(relation)
            if item_status is not None:
                inner_sql += " AND f.status = ?"
                params.append(item_status)

            rows = list(connection.execute(inner_sql, params).fetchall())
            identity_map = resolve_claim_knowledge_ids(
                connection,
                [row["claim_id"] for row in rows if row["claim_id"]],
            )
            knownness_by_item = _knownness_by_feed_item(
                connection,
                user_id=user_id,
                rows=rows,
                identity_map=identity_map,
            )
            candidates = [
                _candidate_from_feed_row(
                    connection,
                    user_id=user_id,
                    row=row,
                    knownness=knownness_by_item[row["id"]],
                    identity_map=identity_map,
                )
                for row in rows
            ]
            ranked = [item for item in rank_candidates(candidates) if not item.hidden]
            rows_by_id = {row["id"]: row for row in rows}
            ranked_rows = [rows_by_id[item.item_id] for item in ranked]
            first_sources = _first_sources_by_event(
                connection,
                list(dict.fromkeys(row["event_id"] for row in ranked_rows)),
            )
            source_candidates = []
            for item in ranked:
                feed_row = rows_by_id[item.item_id]
                identity_label, identity_confidence = _identity_for_claim(
                    connection,
                    feed_row["claim_id"],
                    identity_map=identity_map,
                )
                source_candidates.append(
                    _source_candidate_from_feed_row(
                        feed_row,
                        knownness=knownness_by_item[item.item_id],
                        identity_label=identity_label,
                        identity_confidence=identity_confidence,
                        source=first_sources.get(feed_row["event_id"]),
                    )
                )
            projection = project_candidates(source_candidates)
            additional_by_id = {
                card.displayed_id: [source.to_source_evidence() for source in card.additional_sources]
                for card in projection.cards
                if card.action != "hide"
            }
            evidence_count_by_id = {
                card.displayed_id: card.independent_evidence_count
                for card in projection.cards
                if card.action != "hide"
            }
            surfacing = {"CORRECTION", "DETAIL", "STATE_UPDATE", "UNRESOLVED_CONTRADICTION"}
            restored_ids: set[str] = set()
            for card in projection.cards:
                displayed = rows_by_id.get(card.displayed_id)
                displayed_revision = _revision_class_from_delta(
                    displayed["delta_type"] if displayed is not None else None
                )
                if displayed_revision not in surfacing:
                    continue
                restored_ids.update(source.candidate_id for source in card.additional_sources)
                additional_by_id[card.displayed_id] = []
            collapsed_ids = (
                set(projection.additional_source_ids) | set(projection.hidden_ids)
            ) - restored_ids
            ranked = [item for item in ranked if item.item_id not in collapsed_ids]
            try:
                page, next_cursor = paginate_ranked(
                    ranked,
                    cursor=cursor,
                    limit=limit,
                    policy_version=RANKING_POLICY_VERSION,
                )
            except ValueError as exc:
                raise unprocessable("cursor is invalid or from an obsolete ranking version") from exc
            by_id = {row["id"]: row for row in rows}
            page_rows = [by_id[item.item_id] for item in page]
            sources_by_event: dict[str, list[SourceEvidence]] = {}
            event_ids = list(dict.fromkeys(row["event_id"] for row in page_rows))
            if event_ids:
                placeholders = ",".join("?" for _ in event_ids)
                source_rows = connection.execute(
                    f"""
                    SELECT event_id, publisher, kind, title, url, published_at, retrieved_at, evidence
                    FROM event_sources
                    WHERE event_id IN ({placeholders})
                    ORDER BY published_at, id
                    """,  # nosec B608
                    event_ids,
                ).fetchall()
                for source in source_rows:
                    sources_by_event.setdefault(source["event_id"], []).append(
                        SourceEvidence(
                            publisher=source["publisher"],
                            kind=source["kind"],
                            title=source["title"],
                            url=source["url"],
                            published_at=source["published_at"],
                            retrieved_at=source["retrieved_at"],
                            evidence=source["evidence"],
                        )
                    )

            items: list[PublicFeedItem] = []
            created_at = _now_iso()
            ranked_by_id = {item.item_id: item for item in page}
            knownness_for_page = knownness_by_item
            for row in page_rows:
                delivery_id = f"dlv_{secrets.token_urlsafe(10)}"
                connection.execute(
                    "INSERT INTO deliveries (id, feed_item_id, user_id, created_at) VALUES (?, ?, ?, ?)",
                    (delivery_id, row["id"], user_id, created_at),
                )
                if row["claim_id"] is not None:
                    _upsert_delivered(
                        connection,
                        user_id=user_id,
                        claim_id=row["claim_id"],
                        delivery_id=delivery_id,
                        delivered_at=created_at,
                        event_id=row["event_id"],
                        delta_id=row["delta_id"],
                    )
                extras = additional_by_id.get(row["id"], [])
                ranked_item = ranked_by_id[row["id"]]
                known_state, known_confidence = knownness_for_page[row["id"]]
                matched_repos = [
                    MatchedRepository.model_validate(item)
                    for item in json.loads(row["matched_repos_json"])
                ]
                display_inputs = DisplayReasonInputs(
                    ranking_policy_version=ranked_item.policy_version,
                    priority_rule=ranked_item.priority_rule,
                    redundancy_penalty=ranked_item.axes.redundancy_penalty,
                    relation_level=row["relation_level"],
                    relation_reason=row["relation_reason"],
                    matched_topics=tuple(json.loads(row["matched_topics_json"])),
                    matched_repository_names=tuple(item.name for item in matched_repos),
                    importance_level=row["importance_level"],
                    delta_type=row["delta_type"],
                    knownness_state=known_state,
                    knownness_confidence=known_confidence,
                    additional_source_roles=tuple(item.role for item in extras if item.role),
                    independent_evidence_count=evidence_count_by_id.get(row["id"], 1),
                )
                items.append(
                    _row_to_item(
                        row,
                        delivery_id,
                        follows.get(row["event_id"], False),
                        sources_by_event.get(row["event_id"], []),
                        extras,
                        display_inputs=display_inputs,
                    )
                )
            page_ids = {row["id"] for row in page_rows}
            for card in projection.cards:
                if card.displayed_id not in page_ids:
                    continue
                for source in card.additional_sources:
                    extra = rows_by_id.get(source.candidate_id)
                    if extra is None or extra["claim_id"] is None:
                        continue
                    extra_delivery = f"dlv_{secrets.token_urlsafe(10)}"
                    connection.execute(
                        "INSERT INTO deliveries (id, feed_item_id, user_id, created_at) VALUES (?, ?, ?, ?)",
                        (extra_delivery, extra["id"], user_id, created_at),
                    )
                    _upsert_delivered(
                        connection,
                        user_id=user_id,
                        claim_id=extra["claim_id"],
                        delivery_id=extra_delivery,
                        delivered_at=created_at,
                        event_id=extra["event_id"],
                        delta_id=extra["delta_id"],
                    )

            return items, next_cursor

    def mark_read(self, user_id: str, feed_item_id: str) -> dict:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT id, status FROM feed_items WHERE id = ? AND user_id = ?",
                (feed_item_id, user_id),
            ).fetchone()
            if row is None:
                raise not_found("Feed item was not found")
            connection.execute(
                "UPDATE feed_items SET status = 'read' WHERE id = ? AND user_id = ?",
                (feed_item_id, user_id),
            )
            _record_read(connection, user_id=user_id, feed_item_id=feed_item_id)
            record_session_outcome(
                connection,
                user_id=user_id,
                kind=KIND_DETAIL_READ,
                feed_item_id=feed_item_id,
            )
        return {"feed_item_id": feed_item_id, "status": "read"}

    def save_feedback(self, user_id: str, feed_item_id: str, feedback_type: str) -> dict:
        if not is_allowed_feedback_type(feedback_type):
            raise unprocessable("feedback type is invalid")
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT f.id, f.status, f.event_id, f.delta_id, m.claim_id
                FROM feed_items f
                LEFT JOIN delta_claim_map m ON m.delta_id = f.delta_id
                WHERE f.id = ? AND f.user_id = ?
                """,
                (feed_item_id, user_id),
            ).fetchone()
            if row is None:
                raise not_found("Feed item was not found")
            event_id = row["event_id"]
            delta_id = row["delta_id"]
            claim_id = row["claim_id"]
            family = resolve_write_family(
                feedback_type=feedback_type,
                latest_family=latest_family_for_item(
                    connection,
                    user_id=user_id,
                    feed_item_id=feed_item_id,
                ),
            )
            now = _next_created_at(
                connection,
                user_id=user_id,
                feed_item_id=feed_item_id,
            )
            _supersede_family(
                connection,
                user_id=user_id,
                feed_item_id=feed_item_id,
                family=family,
            )
            feedback_id = f"fb_{secrets.token_urlsafe(8)}"
            connection.execute(
                """
                INSERT INTO feedback (
                    id, feed_item_id, user_id, type, created_at,
                    event_id, delta_id, claim_id, family, superseded
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    feedback_id,
                    feed_item_id,
                    user_id,
                    feedback_type,
                    now,
                    event_id,
                    delta_id,
                    claim_id,
                    family,
                ),
            )
            if family == FAMILY_KNOWLEDGE and feedback_type in {
                KIND_ALREADY_KNEW,
                KIND_LEARNED_NOW,
            }:
                append_knowledge_evidence(
                    connection,
                    user_id=user_id,
                    kind=feedback_type,
                    source_id=feedback_id,
                    claim_id=claim_id,
                    event_id=event_id,
                    delta_id=delta_id,
                    created_at=now,
                )
            _apply_feedback_derived_state(
                connection,
                user_id=user_id,
                feed_item_id=feed_item_id,
                event_id=event_id,
                delta_id=delta_id,
                claim_id=claim_id,
                feedback_type=feedback_type,
                family=family,
                created_at=now,
            )
            apply_feedback_ranking(connection, user_id=user_id)
            current = connection.execute(
                "SELECT status FROM feed_items WHERE id = ?",
                (feed_item_id,),
            ).fetchone()
            item_status = current["status"] if current is not None else row["status"]
            record_session_outcome(
                connection,
                user_id=user_id,
                kind=KIND_FOLLOW if feedback_type == "follow" else KIND_FEEDBACK,
                feed_item_id=feed_item_id,
                feedback_type=feedback_type,
            )
        return {"feed_item_id": feed_item_id, "type": feedback_type, "status": item_status}

    def record_exposures(self, user_id: str, items: list[dict[str, object]]) -> int:
        accepted = 0
        now = int(datetime.now().timestamp())
        with self._database.connect() as connection:
            for item in items:
                delivery_id = str(item["delivery_id"])
                displayed_at = str(item["displayed_at"])
                dwell_raw = item.get("dwell_ms")
                ratio_raw = item.get("visible_ratio")
                dwell_ms = int(dwell_raw) if dwell_raw is not None else None
                visible_ratio = float(ratio_raw) if ratio_raw is not None else None
                detail_opened = bool(item.get("detail_opened") or False)
                if not is_meaningful_display(
                    dwell_ms=dwell_ms,
                    visible_ratio=visible_ratio,
                    detail_opened=detail_opened,
                ):
                    # Too-brief or tiny visibility stays delivered. Do not write
                    # exposures or KIND_DISPLAYED — a later meaningful POST
                    # for the same delivery_id must still be able to count.
                    continue
                delivery = connection.execute(
                    """
                    SELECT d.id, d.feed_item_id, f.delta_id, f.event_id, m.claim_id
                    FROM deliveries d
                    JOIN feed_items f ON f.id = d.feed_item_id
                    LEFT JOIN delta_claim_map m ON m.delta_id = f.delta_id
                    WHERE d.id = ? AND d.user_id = ? AND f.user_id = ?
                    """,
                    (delivery_id, user_id, user_id),
                ).fetchone()
                if delivery is None:
                    continue
                inserted = connection.execute(
                    """
                    INSERT OR IGNORE INTO exposures (
                        delivery_id, user_id, displayed_at, created_at,
                        dwell_ms, visible_ratio, policy_version, detail_opened
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        delivery_id,
                        user_id,
                        displayed_at,
                        now,
                        dwell_ms,
                        visible_ratio,
                        POLICY_VERSION,
                        int(detail_opened),
                    ),
                ).rowcount
                if delivery["claim_id"] is not None:
                    _upsert_displayed(
                        connection,
                        user_id=user_id,
                        claim_id=delivery["claim_id"],
                        delivery_id=delivery_id,
                        displayed_at=displayed_at,
                        event_id=delivery["event_id"],
                        delta_id=delivery["delta_id"],
                    )
                if inserted:
                    record_session_outcome(
                        connection,
                        user_id=user_id,
                        kind=KIND_CARD_DISPLAYED,
                        feed_item_id=str(delivery["feed_item_id"]),
                    )
                accepted += inserted
        return accepted
