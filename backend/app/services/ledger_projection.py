from __future__ import annotations

import hashlib
from urllib.parse import urlparse

from app.database import Database
from app.db.projection_schema import ensure_projection_schema


class LedgerProjector:
    def __init__(self, database: Database) -> None:
        self._database = database
        ensure_projection_schema(database)

    def project_event(self, event_id: str) -> None:
        with self._database.connect() as connection:
            event = connection.execute(
                "SELECT * FROM ledger_events WHERE id = ?",
                (event_id,),
            ).fetchone()
            if event is None:
                raise ValueError(f"ledger event {event_id} not found")
            claims = connection.execute(
                """
                SELECT c.*, r.relation_type, r.prior_claim_id
                FROM state_claims c
                JOIN claim_relations r ON r.new_claim_id = c.id
                WHERE c.event_id = ?
                ORDER BY c.valid_at, c.source_updated_at, c.id
                """,
                (event_id,),
            ).fetchall()
            if not claims:
                raise ValueError(f"ledger event {event_id} has no state claims")

            meaningful_claims = [
                claim for claim in claims if claim["relation_type"] != "NON_NOVEL"
            ]
            if not meaningful_claims:
                raise RuntimeError(f"ledger event {event_id} has no meaningful claims")

            # An unresolved contradiction is observable information, but not a new
            # current truth. Keep the last non-conflicting state as currentState while
            # projecting the contradiction itself as a Delta with reduced confidence.
            settled_claims = [
                claim
                for claim in meaningful_claims
                if claim["relation_type"] != "UNRESOLVED_CONTRADICTION"
            ]
            if not settled_claims:
                raise RuntimeError(f"ledger event {event_id} has no settled state claim")
            latest_state = settled_claims[-1]
            latest_observation = claims[-1]
            current_confidence = (
                "low"
                if meaningful_claims[-1]["relation_type"] == "UNRESOLVED_CONTRADICTION"
                else "high"
            )
            connection.execute(
                """
                INSERT INTO events (
                    id, title, summary, current_phase, current_summary,
                    current_since, current_confidence, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    summary = excluded.summary,
                    current_phase = excluded.current_phase,
                    current_summary = excluded.current_summary,
                    current_since = excluded.current_since,
                    current_confidence = excluded.current_confidence,
                    updated_at = excluded.updated_at
                """,
                (
                    event_id,
                    event["title"],
                    latest_state["detail_text"] or latest_state["value_text"],
                    latest_state["value_text"],
                    latest_state["detail_text"] or latest_state["value_text"],
                    latest_state["valid_at"],
                    current_confidence,
                    latest_observation["source_updated_at"] or latest_observation["valid_at"],
                ),
            )

            # Public Event/Delta/Source tables are derived state. Reconcile them from
            # the ledger on every projection so arrival-order reclassification cannot
            # leave a stale delta visible after it becomes NON_NOVEL.
            connection.execute("UPDATE deltas SET active = 0 WHERE event_id = ?", (event_id,))
            connection.execute("DELETE FROM event_timeline WHERE event_id = ?", (event_id,))
            connection.execute(
                """
                DELETE FROM event_source_claim_map
                WHERE source_id IN (SELECT id FROM event_sources WHERE event_id = ?)
                """,
                (event_id,),
            )
            connection.execute("DELETE FROM event_sources WHERE event_id = ?", (event_id,))

            by_id = {claim["id"]: claim for claim in claims}
            for claim in claims:
                relation_type = claim["relation_type"]
                if relation_type == "NON_NOVEL":
                    continue
                prior = by_id.get(claim["prior_claim_id"])
                delta_id = self._stable_id("delta", claim["id"])
                before = prior["value_text"] if prior is not None else ""
                after = claim["value_text"]
                summary = claim["detail_text"] or f"{before} -> {after}".strip(" ->")
                occurred_at = claim["source_updated_at"] or claim["valid_at"]
                connection.execute(
                    """
                    INSERT INTO deltas (
                        id, event_id, type, summary, before_text, after_text, occurred_at, active
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                    ON CONFLICT(id) DO UPDATE SET
                        type = excluded.type,
                        summary = excluded.summary,
                        before_text = excluded.before_text,
                        after_text = excluded.after_text,
                        occurred_at = excluded.occurred_at,
                        active = 1
                    """,
                    (
                        delta_id,
                        event_id,
                        relation_type.lower(),
                        summary,
                        before,
                        after,
                        occurred_at,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO delta_claim_map (delta_id, claim_id, event_id)
                    VALUES (?, ?, ?)
                    ON CONFLICT(delta_id) DO UPDATE SET
                        claim_id = excluded.claim_id,
                        event_id = excluded.event_id
                    """,
                    (delta_id, claim["id"], event_id),
                )
                timeline_id = self._stable_id("tl", claim["id"])
                timeline_type = self._timeline_type(relation_type, after)
                connection.execute(
                    """
                    INSERT INTO event_timeline (
                        id, event_id, delta_id, type, occurred_at, title,
                        description, state_before, state_after
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        timeline_id,
                        event_id,
                        delta_id,
                        timeline_type,
                        occurred_at,
                        event["title"],
                        summary,
                        before or None,
                        after,
                    ),
                )
                evidence_rows = connection.execute(
                    """
                    SELECT e.*, o.source_type AS evidence_source_type,
                           o.source_key AS evidence_source_key
                    FROM claim_evidence e
                    JOIN observations o ON o.id = e.observation_id
                    WHERE e.claim_id = ?
                    ORDER BY e.id
                    """,
                    (claim["id"],),
                ).fetchall()
                for evidence in evidence_rows:
                    source_id = self._stable_id("src", evidence["id"])
                    evidence_source_type = evidence["evidence_source_type"]
                    evidence_source_key = evidence["evidence_source_key"]
                    publisher = self._publisher(
                        evidence_source_type,
                        evidence_source_key,
                        evidence["original_url"],
                    )
                    connection.execute(
                        """
                        INSERT INTO event_sources (
                            id, event_id, publisher, kind, title, url,
                            published_at, retrieved_at, evidence
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            source_id,
                            event_id,
                            publisher,
                            evidence_source_type,
                            event["title"],
                            evidence["original_url"],
                            evidence["published_at"] or claim["valid_at"],
                            evidence["retrieved_at"],
                            evidence["evidence_text"],
                        ),
                    )
                    connection.execute(
                        """
                        INSERT INTO event_source_claim_map (source_id, claim_id, evidence_id)
                        VALUES (?, ?, ?)
                        """,
                        (source_id, claim["id"], evidence["id"]),
                    )

            connection.execute(
                """
                UPDATE feed_items
                SET dismissed = 1
                WHERE event_id = ?
                  AND delta_id IN (SELECT id FROM deltas WHERE event_id = ? AND active = 0)
                """,
                (event_id, event_id),
            )
            connection.execute(
                """
                UPDATE feed_items
                SET dismissed = 0
                WHERE event_id = ?
                  AND delta_id IN (SELECT id FROM deltas WHERE event_id = ? AND active = 1)
                  AND NOT EXISTS (
                      SELECT 1 FROM feedback
                      WHERE feedback.feed_item_id = feed_items.id
                        AND feedback.type = 'not_relevant'
                  )
                """,
                (event_id, event_id),
            )

    @staticmethod
    def _publisher(source_type: str, source_key: str, original_url: str) -> str:
        if source_type.startswith("github_"):
            return "GitHub"
        if source_type == "osv":
            return "OSV"
        if source_type == "statuspage":
            return "Statuspage"
        if source_type in {"rss_atom", "json_feed"}:
            hostname = urlparse(original_url).hostname
            return hostname or source_key
        return source_key or source_type

    @staticmethod
    def _timeline_type(relation_type: str, after: str) -> str:
        if relation_type == "NEW_FACT":
            return "announced"
        if relation_type == "DETAIL":
            return "information_added"
        if relation_type == "CORRECTION":
            return "corrected"
        if relation_type == "STATE_UPDATE" and after == "resolved":
            return "resolved"
        return "state_changed"

    @staticmethod
    def _stable_id(prefix: str, raw: str) -> str:
        return f"{prefix}_{hashlib.sha256(raw.encode()).hexdigest()[:24]}"