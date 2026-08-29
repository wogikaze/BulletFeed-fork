"""Offline, versioned preference learning from typed feedback.

Learned weights overlay Relation/Importance ranking only. Training never
writes Event, Claim, Delta, or Observation rows. Blind Gold labels are not
a legal training split.

Signal polarity and decay are documented in ADR-0013.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.feedback_signals import RANKING_FEATURE_TYPES
from app.services.user_interest import detect_concepts_in_text

TRAINING_SCHEMA_VERSION = "preference-training-v1"
POLICY_VERSION = "offline-preference-v1"
FEATURE_KIND_SOURCE_TYPE = "source_type"
FEATURE_KIND_CONCEPT = "concept"
MIN_EVIDENCE = 3
DECAY_HALF_LIFE_SECONDS = 30 * 24 * 60 * 60
RANK_SCALE = 25
IMPLICIT_RANK_CAP = 40
EXPLICIT_PROTECTED_RANK_CAP = 20

# Positive / negative masses. already_knew is a weak implicit signal so it
# cannot outrank an explicit topic or selected repository by default.
SIGNAL_WEIGHTS: dict[str, float] = {
    "important": 1.0,
    "follow": 0.8,
    "learned_now": 0.35,
    "already_knew": 0.15,
    "not_relevant": -1.0,
    "less_like_this": -0.8,
}

TrainingSplit = Literal["train", "holdout"]
FeedbackSignal = Literal[
    "important",
    "not_relevant",
    "follow",
    "already_knew",
    "learned_now",
    "less_like_this",
]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TrainingExample(_StrictModel):
    user_id: str = Field(min_length=1)
    feed_item_id: str = Field(min_length=1)
    feedback_type: FeedbackSignal
    created_at: int
    feature_kind: Literal["source_type", "concept"]
    feature_value: str = Field(min_length=1)
    split: TrainingSplit

    @field_validator("split")
    @classmethod
    def reject_blind_labels(cls, value: str) -> str:
        if value == "blind":
            raise ValueError("training input must exclude blind labels")
        return value


class TrainingBatch(_StrictModel):
    schema_version: str
    policy_version: str
    user_id: str = Field(min_length=1)
    examples: list[TrainingExample] = Field(default_factory=list)

    @field_validator("schema_version")
    @classmethod
    def schema_must_match(cls, value: str) -> str:
        if value != TRAINING_SCHEMA_VERSION:
            raise ValueError(f"unsupported training schema_version: {value}")
        return value

    @field_validator("policy_version")
    @classmethod
    def policy_must_match(cls, value: str) -> str:
        if value != POLICY_VERSION:
            raise ValueError(f"unsupported policy_version: {value}")
        return value

    @field_validator("examples")
    @classmethod
    def examples_must_belong_to_user(cls, value: list[TrainingExample], info) -> list[TrainingExample]:
        user_id = info.data.get("user_id")
        if user_id is None:
            return value
        for example in value:
            if example.user_id != user_id:
                raise ValueError("training example user_id does not match batch user_id")
            if example.split == "blind":
                raise ValueError("training input must exclude blind labels")
        return value


@dataclass(frozen=True)
class PreferenceWeight:
    feature_kind: str
    feature_value: str
    weight: float
    evidence_count: int
    positive_mass: float
    negative_mass: float


@dataclass(frozen=True)
class UserPreferenceState:
    policy_version: str
    schema_version: str
    user_id: str
    trained_at: int
    evidence_count: int
    fingerprint: str
    weights: tuple[PreferenceWeight, ...]

    def inspect(self) -> tuple[PreferenceWeight, ...]:
        return self.weights

    def weight_map(self) -> dict[tuple[str, str], PreferenceWeight]:
        return {(item.feature_kind, item.feature_value): item for item in self.weights}

    def is_sparse(self) -> bool:
        return self.evidence_count < MIN_EVIDENCE


@dataclass(frozen=True)
class PreferenceOverlay:
    rank_delta: int
    debug: str
    applied: bool


def decay_factor(created_at: int, as_of: int) -> float:
    """Exponential decay with a 30-day half-life. Replay uses batch as_of."""
    age = max(0, int(as_of) - int(created_at))
    return 0.5 ** (age / DECAY_HALF_LIFE_SECONDS)


def empty_preference_state(user_id: str, *, trained_at: int = 0) -> UserPreferenceState:
    return UserPreferenceState(
        policy_version=POLICY_VERSION,
        schema_version=TRAINING_SCHEMA_VERSION,
        user_id=user_id,
        trained_at=trained_at,
        evidence_count=0,
        fingerprint=_fingerprint(user_id, (), trained_at),
        weights=(),
    )


def validate_training_batch(batch: TrainingBatch | Mapping[str, object]) -> TrainingBatch:
    if isinstance(batch, TrainingBatch):
        parsed = batch
    else:
        parsed = TrainingBatch.model_validate(batch)
    if any(example.split == "blind" for example in parsed.examples):
        raise ValueError("training input must exclude blind labels")
    return parsed


def train_preference(batch: TrainingBatch | Mapping[str, object]) -> UserPreferenceState:
    parsed = validate_training_batch(batch)
    train_examples = tuple(example for example in parsed.examples if example.split == "train")
    as_of = max((example.created_at for example in train_examples), default=0)
    buckets: dict[tuple[str, str], list[TrainingExample]] = {}
    for example in train_examples:
        buckets.setdefault((example.feature_kind, example.feature_value), []).append(example)

    weights: list[PreferenceWeight] = []
    total_evidence = 0
    for (kind, value), group in sorted(buckets.items()):
        evidence = len(group)
        total_evidence += evidence
        positive = 0.0
        negative = 0.0
        for example in group:
            mass = SIGNAL_WEIGHTS[example.feedback_type] * decay_factor(example.created_at, as_of)
            if mass >= 0:
                positive += mass
            else:
                negative += -mass
        net = positive - negative
        if evidence < MIN_EVIDENCE:
            net = 0.0
        weights.append(
            PreferenceWeight(
                feature_kind=kind,
                feature_value=value,
                weight=round(net, 4),
                evidence_count=evidence,
                positive_mass=round(positive, 4),
                negative_mass=round(negative, 4),
            )
        )

    if total_evidence < MIN_EVIDENCE:
        weights = [
            PreferenceWeight(
                feature_kind=item.feature_kind,
                feature_value=item.feature_value,
                weight=0.0,
                evidence_count=item.evidence_count,
                positive_mass=item.positive_mass,
                negative_mass=item.negative_mass,
            )
            for item in weights
        ]

    weights.sort(key=lambda item: (item.feature_kind, item.feature_value))
    return UserPreferenceState(
        policy_version=POLICY_VERSION,
        schema_version=TRAINING_SCHEMA_VERSION,
        user_id=parsed.user_id,
        trained_at=as_of,
        evidence_count=total_evidence,
        fingerprint=_fingerprint(parsed.user_id, train_examples, as_of),
        weights=tuple(weights),
    )


def collect_training_examples(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    reset_at: int,
) -> tuple[TrainingExample, ...]:
    rows = connection.execute(
        """
        WITH latest AS (
            SELECT
                fb.feed_item_id AS feed_item_id,
                fb.type AS feedback_type,
                fb.created_at AS created_at,
                COALESCE(le.source_type, 'unknown') AS source_type,
                COALESCE(e.title, f.title, '') AS title,
                COALESCE(e.summary, '') AS summary
            FROM (
                SELECT
                    user_id,
                    feed_item_id,
                    type,
                    created_at,
                    ROW_NUMBER() OVER (
                        PARTITION BY user_id, feed_item_id, COALESCE(
                            family,
                            CASE type
                                WHEN 'important' THEN 'ranking'
                                WHEN 'not_relevant' THEN 'ranking'
                                WHEN 'already_knew' THEN 'knowledge'
                                WHEN 'learned_now' THEN 'knowledge'
                                WHEN 'follow' THEN 'follow'
                                WHEN 'less_like_this' THEN 'preference'
                                ELSE type
                            END
                        )
                        ORDER BY created_at DESC, id DESC
                    ) AS rn
                FROM feedback
                WHERE user_id = ? AND created_at > ?
            ) fb
            JOIN feed_items f ON f.id = fb.feed_item_id AND f.user_id = fb.user_id
            LEFT JOIN events e ON e.id = f.event_id
            LEFT JOIN ledger_events le ON le.id = f.event_id
            WHERE fb.rn = 1 AND fb.type != 'undo'
        )
        SELECT feed_item_id, feedback_type, created_at, source_type, title, summary
        FROM latest
        ORDER BY created_at, feed_item_id
        """,
        (user_id, reset_at),
    ).fetchall()
    examples: list[TrainingExample] = []
    for row in rows:
        feedback_type = row["feedback_type"]
        if feedback_type not in SIGNAL_WEIGHTS:
            continue
        created_at = int(row["created_at"])
        examples.append(
            TrainingExample(
                user_id=user_id,
                feed_item_id=row["feed_item_id"],
                feedback_type=feedback_type,
                created_at=created_at,
                feature_kind=FEATURE_KIND_SOURCE_TYPE,
                feature_value=row["source_type"] or "unknown",
                split="train",
            )
        )
        text = " ".join(part for part in (row["title"], row["summary"]) if part)
        for concept_id in detect_concepts_in_text(text):
            examples.append(
                TrainingExample(
                    user_id=user_id,
                    feed_item_id=row["feed_item_id"],
                    feedback_type=feedback_type,
                    created_at=created_at,
                    feature_kind=FEATURE_KIND_CONCEPT,
                    feature_value=concept_id,
                    split="train",
                )
            )
    return tuple(examples)


def train_user_preference(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    reset_at: int,
) -> UserPreferenceState:
    examples = collect_training_examples(connection, user_id=user_id, reset_at=reset_at)
    batch = TrainingBatch(
        schema_version=TRAINING_SCHEMA_VERSION,
        policy_version=POLICY_VERSION,
        user_id=user_id,
        examples=list(examples),
    )
    return train_preference(batch)


def persist_user_preference(connection: sqlite3.Connection, state: UserPreferenceState) -> None:
    connection.execute("DELETE FROM user_preference_weights WHERE user_id = ?", (state.user_id,))
    connection.execute("DELETE FROM user_preference_models WHERE user_id = ?", (state.user_id,))
    connection.execute(
        """
        INSERT INTO user_preference_models (
            user_id, policy_version, schema_version, evidence_count,
            fingerprint, trained_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            state.user_id,
            state.policy_version,
            state.schema_version,
            state.evidence_count,
            state.fingerprint,
            state.trained_at,
        ),
    )
    for item in state.weights:
        connection.execute(
            """
            INSERT INTO user_preference_weights (
                user_id, feature_kind, feature_value, weight, evidence_count,
                positive_mass, negative_mass, policy_version, trained_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                state.user_id,
                item.feature_kind,
                item.feature_value,
                item.weight,
                item.evidence_count,
                item.positive_mass,
                item.negative_mass,
                state.policy_version,
                state.trained_at,
            ),
        )


def inspect_user_preference(
    connection: sqlite3.Connection,
    *,
    user_id: str,
) -> UserPreferenceState:
    header = connection.execute(
        """
        SELECT policy_version, schema_version, evidence_count, fingerprint, trained_at
        FROM user_preference_models
        WHERE user_id = ?
        """,
        (user_id,),
    ).fetchone()
    if header is None:
        return empty_preference_state(user_id)
    weights = tuple(
        PreferenceWeight(
            feature_kind=row["feature_kind"],
            feature_value=row["feature_value"],
            weight=float(row["weight"]),
            evidence_count=int(row["evidence_count"]),
            positive_mass=float(row["positive_mass"]),
            negative_mass=float(row["negative_mass"]),
        )
        for row in connection.execute(
            """
            SELECT feature_kind, feature_value, weight, evidence_count,
                   positive_mass, negative_mass
            FROM user_preference_weights
            WHERE user_id = ?
            ORDER BY feature_kind, feature_value
            """,
            (user_id,),
        )
    )
    return UserPreferenceState(
        policy_version=header["policy_version"],
        schema_version=header["schema_version"],
        user_id=user_id,
        trained_at=int(header["trained_at"]),
        evidence_count=int(header["evidence_count"]),
        fingerprint=header["fingerprint"],
        weights=weights,
    )


def reset_user_preference(connection: sqlite3.Connection, *, user_id: str) -> UserPreferenceState:
    connection.execute("DELETE FROM user_preference_weights WHERE user_id = ?", (user_id,))
    connection.execute("DELETE FROM user_preference_models WHERE user_id = ?", (user_id,))
    return empty_preference_state(user_id)


def train_and_persist_user_preference(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    reset_at: int,
) -> UserPreferenceState:
    state = train_user_preference(connection, user_id=user_id, reset_at=reset_at)
    persist_user_preference(connection, state)
    return state


def preference_overlay(
    state: UserPreferenceState,
    *,
    source_type: str,
    text: str,
    has_explicit_authority: bool,
) -> PreferenceOverlay:
    """Rank-only overlay. Explicit topic/repo matches stay stronger than implicit weights."""
    if state.is_sparse():
        return PreferenceOverlay(rank_delta=0, debug="", applied=False)

    source = _active_weight(state, FEATURE_KIND_SOURCE_TYPE, source_type)
    concept_total = 0.0
    concept_hits: list[str] = []
    for concept_id in detect_concepts_in_text(text):
        item = _active_weight(state, FEATURE_KIND_CONCEPT, concept_id)
        if item is None:
            continue
        concept_total += item.weight
        concept_hits.append(concept_id)

    raw = (source.weight if source is not None else 0.0) + 0.5 * concept_total
    if raw == 0.0 and source is None and not concept_hits:
        return PreferenceOverlay(rank_delta=0, debug="", applied=False)

    cap = EXPLICIT_PROTECTED_RANK_CAP if has_explicit_authority else IMPLICIT_RANK_CAP
    delta = int(max(-cap, min(cap, round(raw * RANK_SCALE))))
    if delta == 0 and source is None and not concept_hits:
        return PreferenceOverlay(rank_delta=0, debug="", applied=False)

    parts = []
    if source is not None:
        parts.append(f"{source.feature_value}={source.weight:.3f}")
    if concept_hits:
        parts.append("concepts=" + ",".join(concept_hits))
    authority = "explicit-protected" if has_explicit_authority else "implicit"
    debug = (
        f"Personalized from offline preference ({authority}; {'; '.join(parts) or 'zero'}) "
        f"[{POLICY_VERSION}]."
    )
    return PreferenceOverlay(rank_delta=delta, debug=debug, applied=True)


def score_with_preference(
    state: UserPreferenceState,
    *,
    source_type: str,
    text: str,
    baseline: float,
    has_explicit_authority: bool = False,
) -> float:
    overlay = preference_overlay(
        state,
        source_type=source_type,
        text=text,
        has_explicit_authority=has_explicit_authority,
    )
    return round(baseline + overlay.rank_delta / 100.0, 6)


def _active_weight(
    state: UserPreferenceState,
    feature_kind: str,
    feature_value: str,
) -> PreferenceWeight | None:
    item = state.weight_map().get((feature_kind, feature_value))
    if item is None or item.evidence_count < MIN_EVIDENCE or item.weight == 0:
        return None
    return item


def _fingerprint(user_id: str, examples: Sequence[TrainingExample], trained_at: int) -> str:
    payload = {
        "schema_version": TRAINING_SCHEMA_VERSION,
        "policy_version": POLICY_VERSION,
        "user_id": user_id,
        "trained_at": trained_at,
        "examples": [
            {
                "feed_item_id": example.feed_item_id,
                "feedback_type": example.feedback_type,
                "created_at": example.created_at,
                "feature_kind": example.feature_kind,
                "feature_value": example.feature_value,
                "split": example.split,
            }
            for example in sorted(
                examples,
                key=lambda item: (
                    item.created_at,
                    item.feed_item_id,
                    item.feature_kind,
                    item.feature_value,
                    item.feedback_type,
                ),
            )
        ],
    }
    encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def documented_signal_weights() -> dict[str, float]:
    return dict(SIGNAL_WEIGHTS)


def documented_decay_half_life_seconds() -> int:
    return DECAY_HALF_LIFE_SECONDS


# ranking_feedback v0 tallies remain the count layer; this module owns weights.
assert set(SIGNAL_WEIGHTS) <= set(RANKING_FEATURE_TYPES)
assert math.isclose(SIGNAL_WEIGHTS["already_knew"], 0.15)
