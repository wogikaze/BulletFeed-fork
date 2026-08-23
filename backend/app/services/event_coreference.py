from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from app.database import Database
from app.db.event_identity_schema import ensure_event_identity_schema
from app.db.state_ledger_schema import STATE_LEDGER_SCHEMA
from app.services.claim_semantics import canonicalize_text

CoreferenceLabel = Literal["same_event", "different_event", "uncertain"]
Confidence = Literal["high", "medium", "low"]
_STRUCTURED_FAMILIES = {"statuspage", "github_release", "github_advisory", "osv"}


@dataclass(frozen=True)
class CoreferencePolicy:
    same_event_overlap: float = 0.75
    different_event_overlap: float = 0.30
    same_event_max_days: float = 14.0
    different_event_min_days: float = 60.0
    candidate_recent_days: float = 7.0
    candidate_limit: int = 20
    version: str = "event-coreference-v1"

    @property
    def replay_version(self) -> str:
        return (
            f"{self.version}[same={self.same_event_overlap:.2f},"
            f"different={self.different_event_overlap:.2f},"
            f"same_days={self.same_event_max_days:g},"
            f"different_days={self.different_event_min_days:g},"
            f"limit={self.candidate_limit}]"
        )


DEFAULT_COREFERENCE_POLICY = CoreferencePolicy()


@dataclass(frozen=True)
class CoreferenceInput:
    source_type: str
    source_key: str
    source_event_id: str
    title: str
    subject: str
    valid_at: str

    @property
    def alias_key(self) -> str:
        return identity_alias_key(self.source_type, self.source_key, self.source_event_id)


@dataclass(frozen=True)
class EventCandidate:
    event_id: str
    source_type: str
    source_key: str
    source_event_id: str
    title: str
    created_at: str
    latest_value: str
    latest_detail: str
    latest_valid_at: str
    score: float


@dataclass(frozen=True)
class CandidateSet:
    candidates: tuple[EventCandidate, ...]
    considered: int

    @property
    def size(self) -> int:
        return len(self.candidates)


@dataclass(frozen=True)
class CoreferenceDecision:
    label: CoreferenceLabel
    reason: str
    confidence: Confidence
    candidate_event_id: str | None = None
    score: float = 0.0
    version: str = "event-coreference-v1"


class EventCoreferenceEngine:
    def __init__(
        self,
        database: Database,
        *,
        policy: CoreferencePolicy = DEFAULT_COREFERENCE_POLICY,
        candidate_limit: int | None = None,
    ) -> None:
        resolved_limit = policy.candidate_limit if candidate_limit is None else candidate_limit
        if resolved_limit < 1:
            raise ValueError("candidate_limit must be positive")
        self._database = database
        self._policy = policy
        self._candidate_limit = resolved_limit
        with database.connect() as connection:
            connection.executescript(STATE_LEDGER_SCHEMA)
        ensure_event_identity_schema(database)

    @property
    def decision_version(self) -> str:
        if self._candidate_limit == self._policy.candidate_limit:
            return self._policy.replay_version
        return (
            f"{self._policy.version}[same={self._policy.same_event_overlap:.2f},"
            f"different={self._policy.different_event_overlap:.2f},"
            f"same_days={self._policy.same_event_max_days:g},"
            f"different_days={self._policy.different_event_min_days:g},"
            f"limit={self._candidate_limit}]"
        )

    def resolve(self, value: CoreferenceInput, *, user_id: str | None = None) -> CoreferenceDecision:
        alias = self._resolve_alias_record(value.alias_key, user_id=user_id)
        if alias is not None:
            event_id, decision_version = alias
            return self._decision(
                "same_event",
                "stable source identity is mapped by an audited alias",
                "high",
                candidate_event_id=event_id,
                score=1.0,
                version=decision_version,
            )

        candidate_set = self.retrieve_candidates(value, user_id=user_id)
        decisions = [(candidate, self.compare(value, candidate)) for candidate in candidate_set.candidates]
        same = [item for item in decisions if item[1].label == "same_event"]
        if same:
            candidate, decision = max(same, key=lambda item: (item[1].score, item[0].event_id))
            return self._decision(
                decision.label,
                decision.reason,
                decision.confidence,
                candidate_event_id=candidate.event_id,
                score=decision.score,
            )
        uncertain = [item for item in decisions if item[1].label == "uncertain"]
        if uncertain:
            candidate, decision = max(uncertain, key=lambda item: (item[1].score, item[0].event_id))
            return self._decision(
                "uncertain",
                decision.reason,
                "low",
                candidate_event_id=candidate.event_id,
                score=decision.score,
            )
        return self._decision(
            "different_event",
            "no candidate met the conservative same-event threshold",
            "medium",
        )

    def retrieve_candidates(
        self,
        value: CoreferenceInput,
        *,
        user_id: str | None = None,
    ) -> CandidateSet:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT e.*,
                       COALESCE(c.value_text, '') AS latest_value,
                       COALESCE(c.detail_text, '') AS latest_detail,
                       COALESCE(c.valid_at, e.created_at) AS latest_valid_at
                FROM ledger_events e
                LEFT JOIN state_claims c ON c.id = (
                    SELECT c2.id FROM state_claims c2
                    WHERE c2.event_id = e.id
                    ORDER BY c2.valid_at DESC, c2.source_updated_at DESC, c2.id DESC
                    LIMIT 1
                )
                ORDER BY e.created_at DESC, e.id
                LIMIT 250
                """
            ).fetchall()
            considered = 0
            candidates: list[EventCandidate] = []
            for row in rows:
                if not self._visible(connection, row, user_id=user_id):
                    continue
                considered += 1
                score = self._candidate_score(value, row)
                if score < 0.2 and not self._exact_source_scope(value, row):
                    continue
                candidates.append(
                    EventCandidate(
                        event_id=row["id"],
                        source_type=row["source_type"],
                        source_key=row["source_key"],
                        source_event_id=row["source_event_id"],
                        title=row["title"],
                        created_at=row["created_at"],
                        latest_value=row["latest_value"],
                        latest_detail=row["latest_detail"],
                        latest_valid_at=row["latest_valid_at"],
                        score=score,
                    )
                )
        candidates.sort(key=lambda candidate: (-candidate.score, candidate.event_id))
        return CandidateSet(tuple(candidates[: self._candidate_limit]), considered)

    def compare(self, value: CoreferenceInput, candidate: EventCandidate) -> CoreferenceDecision:
        if (
            value.source_type == candidate.source_type
            and value.source_key == candidate.source_key
            and value.source_event_id == candidate.source_event_id
        ):
            return self._decision(
                "same_event",
                "structured source identity is identical",
                "high",
                candidate_event_id=candidate.event_id,
                score=1.0,
            )
        if (
            value.source_type == candidate.source_type
            and value.source_key == candidate.source_key
            and value.source_type in _STRUCTURED_FAMILIES
            and value.source_event_id != candidate.source_event_id
        ):
            return self._decision(
                "different_event",
                "distinct structured IDs in the same source scope are a hard negative",
                "high",
                candidate_event_id=candidate.event_id,
                score=0.0,
            )

        incoming = canonicalize_text(f"{value.title} {value.subject}")
        existing = canonicalize_text(
            f"{candidate.title} {candidate.latest_value} {candidate.latest_detail}"
        )
        if incoming.versions != existing.versions and (incoming.versions and existing.versions):
            return self._decision(
                "different_event",
                "version identifiers conflict",
                "high",
                candidate_event_id=candidate.event_id,
                score=0.0,
            )

        days = _days_apart(value.valid_at, candidate.latest_valid_at)
        incoming_title = canonicalize_text(value.title)
        existing_title = canonicalize_text(candidate.title)
        if (
            incoming_title.text == existing_title.text
            and len(set(incoming_title.tokens)) >= 2
            and days <= self._policy.different_event_min_days
        ):
            return self._decision(
                "same_event",
                "specific canonical titles match within the extended lifecycle window",
                "medium",
                candidate_event_id=candidate.event_id,
                score=0.95,
            )

        overlap = _token_overlap(incoming.tokens, existing.tokens)
        scope_bonus = 0.15 if value.source_key and value.source_key == candidate.source_key else 0.0
        score = min(1.0, overlap + scope_bonus + (0.1 if days <= 2 else 0.0))
        if overlap >= self._policy.same_event_overlap and days <= self._policy.same_event_max_days:
            return self._decision(
                "same_event",
                "subject/entity tokens strongly overlap within the event time window",
                "medium",
                candidate_event_id=candidate.event_id,
                score=score,
            )
        if (
            overlap <= self._policy.different_event_overlap
            or days > self._policy.different_event_min_days
        ):
            return self._decision(
                "different_event",
                "subject overlap or event time window is insufficient",
                "medium",
                candidate_event_id=candidate.event_id,
                score=score,
            )
        return self._decision(
            "uncertain",
            "candidate evidence is plausible but below the safe merge threshold",
            "low",
            candidate_event_id=candidate.event_id,
            score=score,
        )

    def record_alias(
        self,
        alias_key: str,
        event_id: str,
        *,
        reason: str,
        created_at: str,
        decision_version: str = "manual-v1",
    ) -> None:
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO event_identity_aliases (
                    alias_key, event_id, reason, decision_version, created_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(alias_key) DO UPDATE SET
                    event_id = excluded.event_id,
                    reason = excluded.reason,
                    decision_version = excluded.decision_version,
                    created_at = excluded.created_at
                """,
                (alias_key, event_id, reason, decision_version, created_at),
            )

    def resolve_alias(self, alias_key: str, *, user_id: str | None = None) -> str | None:
        record = self._resolve_alias_record(alias_key, user_id=user_id)
        return record[0] if record is not None else None

    def _resolve_alias_record(
        self,
        alias_key: str,
        *,
        user_id: str | None,
    ) -> tuple[str, str] | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT a.event_id, a.decision_version, e.source_key
                FROM event_identity_aliases a
                JOIN ledger_events e ON e.id = a.event_id
                WHERE a.alias_key = ?
                """,
                (alias_key,),
            ).fetchone()
            if row is None or not self._visible(connection, row, user_id=user_id):
                return None
        return row["event_id"], row["decision_version"]

    @staticmethod
    def _exact_source_scope(value: CoreferenceInput, row) -> bool:
        return value.source_type == row["source_type"] and value.source_key == row["source_key"]

    def _candidate_score(self, value: CoreferenceInput, row) -> float:
        incoming = canonicalize_text(f"{value.title} {value.subject}")
        existing = canonicalize_text(f"{row['title']} {row['latest_value']} {row['latest_detail']}")
        score = _token_overlap(incoming.tokens, existing.tokens)
        if value.source_key and value.source_key == row["source_key"]:
            score += 0.15
        if _days_apart(value.valid_at, row["latest_valid_at"]) <= self._policy.candidate_recent_days:
            score += 0.1
        return min(1.0, score)

    @staticmethod
    def _visible(connection, row, *, user_id: str | None) -> bool:
        event_id = row["event_id"] if "event_id" in row.keys() else row["id"]
        visibility = connection.execute(
            "SELECT restricted FROM event_visibility WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        if visibility is not None and bool(visibility["restricted"]):
            if user_id is None:
                return False
            grant = connection.execute(
                """
                SELECT 1 FROM event_user_access
                WHERE event_id = ? AND user_id = ? AND expires_at > ?
                """,
                (event_id, user_id, int(time.time())),
            ).fetchone()
            return grant is not None

        private_watch = connection.execute(
            "SELECT 1 FROM github_repo_watches WHERE full_name = ? AND private = 1 LIMIT 1",
            (row["source_key"],),
        ).fetchone()
        if private_watch is None:
            return True
        if user_id is None:
            return False
        own_watch = connection.execute(
            """
            SELECT 1 FROM github_repo_watches
            WHERE full_name = ? AND user_id = ? AND private = 1 AND selected = 1
            LIMIT 1
            """,
            (row["source_key"], user_id),
        ).fetchone()
        return own_watch is not None

    def _decision(
        self,
        label: CoreferenceLabel,
        reason: str,
        confidence: Confidence,
        *,
        candidate_event_id: str | None = None,
        score: float = 0.0,
        version: str | None = None,
    ) -> CoreferenceDecision:
        return CoreferenceDecision(
            label,
            reason,
            confidence,
            candidate_event_id=candidate_event_id,
            score=score,
            version=version or self.decision_version,
        )


def identity_alias_key(source_type: str, source_key: str, source_event_id: str) -> str:
    return "|".join((source_type, source_key, source_event_id))


def _token_overlap(left: tuple[str, ...], right: tuple[str, ...]) -> float:
    left_set = set(left)
    right_set = set(right)
    union = left_set | right_set
    if not union:
        return 1.0
    return len(left_set & right_set) / len(union)


def _days_apart(left: str, right: str) -> float:
    try:
        left_dt = datetime.fromisoformat(left.replace("Z", "+00:00"))
        right_dt = datetime.fromisoformat(right.replace("Z", "+00:00"))
        if left_dt.tzinfo is None:
            left_dt = left_dt.replace(tzinfo=UTC)
        if right_dt.tzinfo is None:
            right_dt = right_dt.replace(tzinfo=UTC)
        return abs((left_dt - right_dt).total_seconds()) / 86400
    except ValueError:
        return 9999.0
