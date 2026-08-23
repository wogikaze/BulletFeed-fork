from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from app.database import Database
from app.db.event_identity_schema import ensure_event_identity_schema
from app.services.event_coreference import identity_alias_key
from app.services.ledger_projection import LedgerProjector
from app.stores.claim_ledger_store import ClaimLedgerStore


@dataclass(frozen=True)
class EventRepairResult:
    operation: str
    source_event_id: str
    target_event_id: str
    moved_claim_ids: tuple[str, ...]


@dataclass(frozen=True)
class _VisibilitySnapshot:
    restricted: bool
    grants: tuple[tuple[str, int], ...]


class EventIdentityRepairService:
    """Repair derived Event identity while preserving immutable Observation/Evidence rows."""

    def __init__(self, database: Database) -> None:
        self._database = database
        self._ledger = ClaimLedgerStore(database)
        self._projector = LedgerProjector(database)
        ensure_event_identity_schema(database)

    def alias_source_identity(
        self,
        *,
        source_type: str,
        source_key: str,
        source_event_id: str,
        target_event_id: str,
        reason: str,
        created_at: str,
    ) -> EventRepairResult:
        return self._alias(
            source_type=source_type,
            source_key=source_key,
            source_event_id=source_event_id,
            target_event_id=target_event_id,
            reason=reason,
            created_at=created_at,
            record=True,
        )

    def merge_events(
        self,
        *,
        source_event_id: str,
        target_event_id: str,
        reason: str,
        created_at: str,
    ) -> EventRepairResult:
        return self._merge(
            source_event_id=source_event_id,
            target_event_id=target_event_id,
            reason=reason,
            created_at=created_at,
            record=True,
        )

    def split_claims(
        self,
        *,
        source_event_id: str,
        claim_ids: tuple[str, ...],
        new_source_event_id: str,
        title: str,
        reason: str,
        created_at: str,
    ) -> EventRepairResult:
        return self._split(
            source_event_id=source_event_id,
            claim_ids=claim_ids,
            new_source_event_id=new_source_event_id,
            title=title,
            reason=reason,
            created_at=created_at,
            record=True,
        )

    def replay_repairs(self) -> tuple[EventRepairResult, ...]:
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM event_identity_repairs ORDER BY created_at, id"
            ).fetchall()
        results: list[EventRepairResult] = []
        for row in rows:
            claim_ids = tuple(json.loads(row["claim_ids_json"]))
            metadata = json.loads(row["metadata_json"] or "{}")
            if row["operation"] == "alias":
                parts = row["source_event_id"].split("|", 2)
                source_type = str(
                    metadata.get("source_type", parts[0] if len(parts) == 3 else "")
                )
                source_key = str(
                    metadata.get("source_key", parts[1] if len(parts) == 3 else "")
                )
                source_identity = str(
                    metadata.get("source_event_id", parts[2] if len(parts) == 3 else "")
                )
                if source_type and source_identity and self._event_exists(row["target_event_id"]):
                    results.append(
                        self._alias(
                            source_type=source_type,
                            source_key=source_key,
                            source_event_id=source_identity,
                            target_event_id=row["target_event_id"],
                            reason=row["reason"],
                            created_at=row["created_at"],
                            record=False,
                        )
                    )
            elif row["operation"] == "merge":
                if self._event_exists(row["source_event_id"]) and self._event_exists(
                    row["target_event_id"]
                ):
                    results.append(
                        self._merge(
                            source_event_id=row["source_event_id"],
                            target_event_id=row["target_event_id"],
                            reason=row["reason"],
                            created_at=row["created_at"],
                            record=False,
                        )
                    )
            elif row["operation"] == "split":
                if self._claims_belong_to_event(claim_ids, row["target_event_id"]):
                    continue
                if self._event_exists(row["source_event_id"]):
                    results.append(
                        self._split(
                            source_event_id=row["source_event_id"],
                            claim_ids=claim_ids,
                            new_source_event_id=str(
                                metadata.get("new_source_event_id", "replayed-split")
                            ),
                            title=str(metadata.get("title", "Repaired Event")),
                            reason=row["reason"],
                            created_at=row["created_at"],
                            record=False,
                            target_event_id=row["target_event_id"],
                        )
                    )
        return tuple(results)

    def _alias(
        self,
        *,
        source_type: str,
        source_key: str,
        source_event_id: str,
        target_event_id: str,
        reason: str,
        created_at: str,
        record: bool,
    ) -> EventRepairResult:
        alias_key = identity_alias_key(source_type, source_key, source_event_id)
        with self._database.connect() as connection:
            self._require_event(connection, target_event_id)
            connection.execute(
                """
                INSERT INTO event_identity_aliases (
                    alias_key, event_id, reason, decision_version, created_at
                ) VALUES (?, ?, ?, 'manual-repair-v1', ?)
                ON CONFLICT(alias_key) DO UPDATE SET
                    event_id = excluded.event_id,
                    reason = excluded.reason,
                    decision_version = excluded.decision_version,
                    created_at = excluded.created_at
                """,
                (alias_key, target_event_id, reason, created_at),
            )
            if record:
                self._record(
                    connection,
                    operation="alias",
                    source_event_id=alias_key,
                    target_event_id=target_event_id,
                    claim_ids=(),
                    metadata={
                        "source_type": source_type,
                        "source_key": source_key,
                        "source_event_id": source_event_id,
                    },
                    reason=reason,
                    created_at=created_at,
                )
        return EventRepairResult("alias", alias_key, target_event_id, ())

    def _merge(
        self,
        *,
        source_event_id: str,
        target_event_id: str,
        reason: str,
        created_at: str,
        record: bool,
    ) -> EventRepairResult:
        if source_event_id == target_event_id:
            raise ValueError("source and target Event must differ")
        with self._database.connect() as connection:
            source = self._require_event(connection, source_event_id)
            self._require_event(connection, target_event_id)
            claim_ids = tuple(
                row["id"]
                for row in connection.execute(
                    "SELECT id FROM state_claims WHERE event_id = ? ORDER BY id",
                    (source_event_id,),
                ).fetchall()
            )
            if not claim_ids:
                raise ValueError("source Event has no claims to merge")
            visibility = self._combine_visibility(
                self._snapshot_visibility(connection, source_event_id),
                self._snapshot_visibility(connection, target_event_id),
            )
            alias_key = identity_alias_key(
                source["source_type"], source["source_key"], source["source_event_id"]
            )
            connection.execute(
                """
                INSERT INTO event_identity_aliases (
                    alias_key, event_id, reason, decision_version, created_at
                ) VALUES (?, ?, ?, 'manual-repair-v1', ?)
                ON CONFLICT(alias_key) DO UPDATE SET
                    event_id = excluded.event_id,
                    reason = excluded.reason,
                    decision_version = excluded.decision_version,
                    created_at = excluded.created_at
                """,
                (alias_key, target_event_id, reason, created_at),
            )
            connection.execute(
                "UPDATE event_identity_aliases SET event_id = ? WHERE event_id = ?",
                (target_event_id, source_event_id),
            )
            connection.execute(
                "UPDATE state_claims SET event_id = ? WHERE event_id = ?",
                (target_event_id, source_event_id),
            )
            connection.execute(
                "DELETE FROM claim_relations WHERE event_id = ? OR event_id = ?",
                (source_event_id, target_event_id),
            )
            if record:
                self._record(
                    connection,
                    operation="merge",
                    source_event_id=source_event_id,
                    target_event_id=target_event_id,
                    claim_ids=claim_ids,
                    metadata={},
                    reason=reason,
                    created_at=created_at,
                )
        self._ledger.rebuild_event_relations(target_event_id)
        self._detach_claim_projections(claim_ids, target_event_id)
        self._retire_event(source_event_id, target_event_id)
        self._projector.project_event(target_event_id)
        self._apply_visibility(target_event_id, visibility)
        return EventRepairResult("merge", source_event_id, target_event_id, claim_ids)

    def _split(
        self,
        *,
        source_event_id: str,
        claim_ids: tuple[str, ...],
        new_source_event_id: str,
        title: str,
        reason: str,
        created_at: str,
        record: bool,
        target_event_id: str | None = None,
    ) -> EventRepairResult:
        unique_ids = tuple(sorted(set(claim_ids)))
        if not unique_ids:
            raise ValueError("split requires at least one claim")
        with self._database.connect() as connection:
            source = self._require_event(connection, source_event_id)
            all_claims = {
                row["id"]
                for row in connection.execute(
                    "SELECT id FROM state_claims WHERE event_id = ?",
                    (source_event_id,),
                ).fetchall()
            }
            if not set(unique_ids) <= all_claims:
                raise ValueError("every split claim must belong to the source Event")
            if set(unique_ids) == all_claims:
                raise ValueError("cannot split every claim")
            visibility = self._snapshot_visibility(connection, source_event_id)
            resolved_target = target_event_id or self._stable_id(
                "evt", f"repair|{source_event_id}|{new_source_event_id}"
            )
            connection.execute(
                """
                INSERT INTO ledger_events (
                    id, source_type, source_key, source_event_id, title, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET title = excluded.title
                """,
                (
                    resolved_target,
                    source["source_type"],
                    source["source_key"],
                    new_source_event_id,
                    title,
                    created_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO events (
                    id, title, summary, current_phase, current_summary,
                    current_since, current_confidence, updated_at
                ) VALUES (?, ?, '', '', '', ?, 'low', ?)
                ON CONFLICT(id) DO NOTHING
                """,
                (resolved_target, title, created_at, created_at),
            )
            for claim_id in unique_ids:
                connection.execute(
                    "UPDATE state_claims SET event_id = ? WHERE id = ?",
                    (resolved_target, claim_id),
                )
            connection.execute(
                "DELETE FROM claim_relations WHERE event_id = ? OR event_id = ?",
                (source_event_id, resolved_target),
            )
            if record:
                self._record(
                    connection,
                    operation="split",
                    source_event_id=source_event_id,
                    target_event_id=resolved_target,
                    claim_ids=unique_ids,
                    metadata={"new_source_event_id": new_source_event_id, "title": title},
                    reason=reason,
                    created_at=created_at,
                )
        self._ledger.rebuild_event_relations(source_event_id)
        self._ledger.rebuild_event_relations(resolved_target)
        self._detach_claim_projections(unique_ids, resolved_target)
        self._projector.project_event(source_event_id)
        self._projector.project_event(resolved_target)
        self._copy_follows(source_event_id, resolved_target)
        self._apply_visibility(resolved_target, visibility)
        return EventRepairResult("split", source_event_id, resolved_target, unique_ids)

    def _detach_claim_projections(
        self,
        claim_ids: tuple[str, ...],
        target_event_id: str,
    ) -> None:
        with self._database.connect() as connection:
            for claim_id in claim_ids:
                source_rows = connection.execute(
                    "SELECT source_id FROM event_source_claim_map WHERE claim_id = ?",
                    (claim_id,),
                ).fetchall()
                for row in source_rows:
                    source_id = row["source_id"]
                    connection.execute(
                        "DELETE FROM event_source_claim_map WHERE source_id = ?",
                        (source_id,),
                    )
                    connection.execute("DELETE FROM event_sources WHERE id = ?", (source_id,))
                delta_rows = connection.execute(
                    "SELECT delta_id FROM delta_claim_map WHERE claim_id = ?",
                    (claim_id,),
                ).fetchall()
                connection.execute(
                    "UPDATE delta_claim_map SET event_id = ? WHERE claim_id = ?",
                    (target_event_id, claim_id),
                )
                for row in delta_rows:
                    delta_id = row["delta_id"]
                    connection.execute(
                        "DELETE FROM event_timeline WHERE delta_id = ?",
                        (delta_id,),
                    )
                    connection.execute(
                        "UPDATE deltas SET event_id = ? WHERE id = ?",
                        (target_event_id, delta_id),
                    )
                    connection.execute(
                        "UPDATE feed_items SET event_id = ? WHERE delta_id = ?",
                        (target_event_id, delta_id),
                    )

    def _retire_event(self, source_event_id: str, target_event_id: str) -> None:
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO event_follows (user_id, event_id, following)
                SELECT user_id, ?, following FROM event_follows WHERE event_id = ?
                ON CONFLICT(user_id, event_id) DO UPDATE SET
                    following = MAX(event_follows.following, excluded.following)
                """,
                (target_event_id, source_event_id),
            )
            connection.execute("DELETE FROM event_follows WHERE event_id = ?", (source_event_id,))
            connection.execute(
                "UPDATE event_impacts SET event_id = ? WHERE event_id = ?",
                (target_event_id, source_event_id),
            )
            connection.execute(
                "UPDATE notifications SET target_id = ? WHERE target_type = 'event' AND target_id = ?",
                (target_event_id, source_event_id),
            )
            source_rows = connection.execute(
                "SELECT id FROM event_sources WHERE event_id = ?",
                (source_event_id,),
            ).fetchall()
            for row in source_rows:
                connection.execute(
                    "DELETE FROM event_source_claim_map WHERE source_id = ?",
                    (row["id"],),
                )
            connection.execute("DELETE FROM event_sources WHERE event_id = ?", (source_event_id,))
            connection.execute("DELETE FROM event_timeline WHERE event_id = ?", (source_event_id,))
            connection.execute("DELETE FROM event_user_access WHERE event_id = ?", (source_event_id,))
            connection.execute("DELETE FROM event_visibility WHERE event_id = ?", (source_event_id,))
            connection.execute("DELETE FROM events WHERE id = ?", (source_event_id,))
            connection.execute("DELETE FROM ledger_events WHERE id = ?", (source_event_id,))

    def _copy_follows(self, source_event_id: str, target_event_id: str) -> None:
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO event_follows (user_id, event_id, following)
                SELECT user_id, ?, following FROM event_follows WHERE event_id = ?
                ON CONFLICT(user_id, event_id) DO UPDATE SET
                    following = MAX(event_follows.following, excluded.following)
                """,
                (target_event_id, source_event_id),
            )

    @staticmethod
    def _require_event(connection, event_id: str):
        event = connection.execute(
            "SELECT * FROM ledger_events WHERE id = ?", (event_id,)
        ).fetchone()
        if event is None:
            raise ValueError(f"ledger Event {event_id} not found")
        return event

    @staticmethod
    def _snapshot_visibility(connection, event_id: str) -> _VisibilitySnapshot:
        row = connection.execute(
            "SELECT restricted FROM event_visibility WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        restricted = bool(row["restricted"]) if row is not None else False
        grants = tuple(
            (grant["user_id"], int(grant["expires_at"]))
            for grant in connection.execute(
                """
                SELECT user_id, expires_at
                FROM event_user_access
                WHERE event_id = ?
                ORDER BY user_id
                """,
                (event_id,),
            ).fetchall()
        )
        return _VisibilitySnapshot(restricted, grants)

    @staticmethod
    def _combine_visibility(
        source: _VisibilitySnapshot,
        target: _VisibilitySnapshot,
    ) -> _VisibilitySnapshot:
        if not source.restricted and not target.restricted:
            return _VisibilitySnapshot(False, ())
        source_grants = dict(source.grants)
        target_grants = dict(target.grants)
        if source.restricted and target.restricted:
            users = source_grants.keys() & target_grants.keys()
            grants = tuple(
                sorted(
                    (user_id, min(source_grants[user_id], target_grants[user_id]))
                    for user_id in users
                )
            )
        elif source.restricted:
            grants = source.grants
        else:
            grants = target.grants
        return _VisibilitySnapshot(True, grants)

    def _apply_visibility(self, event_id: str, snapshot: _VisibilitySnapshot) -> None:
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO event_visibility (event_id, restricted) VALUES (?, ?)
                ON CONFLICT(event_id) DO UPDATE SET restricted = excluded.restricted
                """,
                (event_id, int(snapshot.restricted)),
            )
            connection.execute("DELETE FROM event_user_access WHERE event_id = ?", (event_id,))
            if snapshot.restricted:
                for user_id, expires_at in snapshot.grants:
                    connection.execute(
                        """
                        INSERT INTO event_user_access (event_id, user_id, expires_at)
                        VALUES (?, ?, ?)
                        """,
                        (event_id, user_id, expires_at),
                    )

    def _event_exists(self, event_id: str) -> bool:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM ledger_events WHERE id = ?", (event_id,)
            ).fetchone()
        return row is not None

    def _claims_belong_to_event(self, claim_ids: tuple[str, ...], event_id: str) -> bool:
        if not claim_ids:
            return False
        with self._database.connect() as connection:
            for claim_id in claim_ids:
                row = connection.execute(
                    "SELECT event_id FROM state_claims WHERE id = ?",
                    (claim_id,),
                ).fetchone()
                if row is None or row["event_id"] != event_id:
                    return False
        return True

    def _record(
        self,
        connection,
        *,
        operation: str,
        source_event_id: str,
        target_event_id: str,
        claim_ids: tuple[str, ...],
        metadata: dict[str, object],
        reason: str,
        created_at: str,
    ) -> None:
        raw = "|".join((operation, source_event_id, target_event_id, created_at, *claim_ids))
        connection.execute(
            """
            INSERT INTO event_identity_repairs (
                id, operation, source_event_id, target_event_id,
                claim_ids_json, metadata_json, reason, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO NOTHING
            """,
            (
                self._stable_id("repair", raw),
                operation,
                source_event_id,
                target_event_id,
                json.dumps(claim_ids),
                json.dumps(metadata, sort_keys=True),
                reason,
                created_at,
            ),
        )

    @staticmethod
    def _stable_id(prefix: str, raw: str) -> str:
        return f"{prefix}_{hashlib.sha256(raw.encode()).hexdigest()[:24]}"
