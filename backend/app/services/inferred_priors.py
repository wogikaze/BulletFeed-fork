"""Rebuildable GitHub-inferred interest priors, separate from explicit topics.

Priors are derived from selected repository watches plus typed inference
signals (language, dependency, devDependency, build-tool, repository-topic).
The Event/Claim ledger is never written. Aggregated weights are computed on
read; persisted rows are only the rebuildable per-repository signals.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Literal

from app.db.topic_catalog import canonical_topic

INFERENCE_VERSION = "inferred-priors-v1"
INFERRED_PRIOR_STATE_VERSION = "inferred-prior-state-v1"

SignalType = Literal[
    "language",
    "dependency",
    "dev_dependency",
    "build_tool",
    "repository_topic",
]

SIGNAL_TYPES: tuple[SignalType, ...] = (
    "language",
    "dependency",
    "dev_dependency",
    "build_tool",
    "repository_topic",
)

# Explicit user-selected topics stay stronger by default (0.4–1.0 in user_interest).
SIGNAL_WEIGHTS: dict[SignalType, float] = {
    "language": 0.40,
    "dependency": 0.35,
    "dev_dependency": 0.15,
    "build_tool": 0.20,
    "repository_topic": 0.25,
}

_INFERRED_WEIGHT_CAP = 0.65


@dataclass(frozen=True)
class InferredInterestSignal:
    repository: str
    signal_type: SignalType
    topic_name: str
    weight: float
    inference_version: str
    observed_at: str

    def provenance(self) -> str:
        return (
            f"inferred-prior:{self.inference_version}:{self.signal_type}:"
            f"{self.repository}:{self.topic_name}:{self.observed_at}"
        )


@dataclass(frozen=True)
class InferredPrior:
    topic_key: str
    display_name: str
    weight: float
    sources: tuple[InferredInterestSignal, ...]


@dataclass(frozen=True)
class InferredPriorState:
    version: str
    user_id: str
    inference_version: str
    signal_fingerprint: str
    priors: tuple[InferredPrior, ...]
    signals: tuple[InferredInterestSignal, ...]

    def prior_map(self) -> dict[str, InferredPrior]:
        return {prior.topic_key: prior for prior in self.priors}

    def inspect(self) -> tuple[InferredPrior, ...]:
        return self.priors


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def is_signal_type(value: str) -> bool:
    return value in SIGNAL_WEIGHTS


def display_topic_name(raw: str) -> str:
    cleaned = raw.strip()
    if not cleaned:
        return ""
    canonical = canonical_topic(cleaned)
    return canonical[0] if canonical is not None else cleaned


def topic_key(raw: str) -> str:
    return display_topic_name(raw).casefold()


def make_inferred_signal(
    *,
    repository: str,
    signal_type: SignalType,
    topic_name: str,
    observed_at: str,
    inference_version: str = INFERENCE_VERSION,
) -> InferredInterestSignal | None:
    repo = repository.strip()
    display = display_topic_name(topic_name)
    if not repo or not display or not is_signal_type(signal_type):
        return None
    return InferredInterestSignal(
        repository=repo,
        signal_type=signal_type,
        topic_name=display,
        weight=SIGNAL_WEIGHTS[signal_type],
        inference_version=inference_version,
        observed_at=observed_at,
    )


def _combine_weights(weights: Sequence[float]) -> float:
    acc = 1.0
    for weight in sorted(weights):
        clamped = min(1.0, max(0.0, weight))
        acc *= 1.0 - clamped
    return min(_INFERRED_WEIGHT_CAP, round(1.0 - acc, 4))


def _normalize_signal(signal: InferredInterestSignal) -> InferredInterestSignal:
    display = display_topic_name(signal.topic_name)
    signal_type = signal.signal_type if is_signal_type(signal.signal_type) else "repository_topic"
    return replace(
        signal,
        repository=signal.repository.strip(),
        signal_type=signal_type,
        topic_name=display,
        weight=SIGNAL_WEIGHTS[signal_type],
        inference_version=INFERENCE_VERSION,
    )


def _signal_sort_key(signal: InferredInterestSignal) -> tuple[str, str, str, str]:
    return (signal.repository, signal.signal_type, signal.topic_name.casefold(), signal.observed_at)


def _fingerprint(signals: Sequence[InferredInterestSignal]) -> str:
    payload = [
        {
            "repository": signal.repository,
            "signal_type": signal.signal_type,
            "topic": signal.topic_name,
            "weight": f"{signal.weight:.4f}",
            "version": signal.inference_version,
            "observed_at": signal.observed_at,
        }
        for signal in sorted(signals, key=_signal_sort_key)
    ]
    encoded = json.dumps(
        {"version": INFERRED_PRIOR_STATE_VERSION, "inference": INFERENCE_VERSION, "signals": payload},
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def rebuild_inferred_priors(
    user_id: str,
    signals: Sequence[InferredInterestSignal],
    *,
    selected_repositories: Sequence[str] | None = None,
) -> InferredPriorState:
    selected = None if selected_repositories is None else {name.strip() for name in selected_repositories}
    rebuilt: list[InferredInterestSignal] = []
    seen: set[tuple[str, str, str]] = set()
    for signal in signals:
        normalized = _normalize_signal(signal)
        if not normalized.repository or not normalized.topic_name:
            continue
        if selected is not None and normalized.repository not in selected:
            continue
        key = (normalized.repository, normalized.signal_type, normalized.topic_name.casefold())
        if key in seen:
            continue
        seen.add(key)
        rebuilt.append(normalized)
    rebuilt.sort(key=_signal_sort_key)

    grouped: dict[str, list[InferredInterestSignal]] = {}
    displays: dict[str, str] = {}
    for signal in rebuilt:
        key = topic_key(signal.topic_name)
        grouped.setdefault(key, []).append(signal)
        displays.setdefault(key, signal.topic_name)

    priors = [
        InferredPrior(
            topic_key=key,
            display_name=displays[key],
            weight=_combine_weights(tuple(item.weight for item in group)),
            sources=tuple(sorted(group, key=_signal_sort_key)),
        )
        for key, group in grouped.items()
    ]
    priors.sort(key=lambda item: (-item.weight, item.topic_key))
    rebuilt_tuple = tuple(rebuilt)
    return InferredPriorState(
        version=INFERRED_PRIOR_STATE_VERSION,
        user_id=user_id,
        inference_version=INFERENCE_VERSION,
        signal_fingerprint=_fingerprint(rebuilt_tuple),
        priors=tuple(priors),
        signals=rebuilt_tuple,
    )


def empty_inferred_priors(user_id: str) -> InferredPriorState:
    return rebuild_inferred_priors(user_id, ())


def reset_inferred_priors(user_id: str) -> InferredPriorState:
    """Forget inferred priors only. Explicit topics are out of scope."""
    return empty_inferred_priors(user_id)


def withdraw_repository(
    state: InferredPriorState,
    repository: str,
) -> InferredPriorState:
    remaining = tuple(signal for signal in state.signals if signal.repository != repository.strip())
    return rebuild_inferred_priors(state.user_id, remaining)


def selected_repository_names(connection: sqlite3.Connection, user_id: str) -> tuple[str, ...]:
    return tuple(
        row["full_name"]
        for row in connection.execute(
            """
            SELECT full_name
            FROM github_repo_watches
            WHERE user_id = ? AND selected = 1
            ORDER BY full_name
            """,
            (user_id,),
        )
    )


def load_inferred_signals(
    connection: sqlite3.Connection,
    user_id: str,
) -> tuple[InferredInterestSignal, ...]:
    rows = connection.execute(
        """
        SELECT repository, signal_type, topic_name, weight, inference_version, observed_at
        FROM github_inferred_signals
        WHERE user_id = ?
        ORDER BY repository, signal_type, topic_name
        """,
        (user_id,),
    ).fetchall()
    signals: list[InferredInterestSignal] = []
    for row in rows:
        signal_type = row["signal_type"]
        if not is_signal_type(signal_type):
            continue
        signals.append(
            InferredInterestSignal(
                repository=row["repository"],
                signal_type=signal_type,
                topic_name=row["topic_name"],
                weight=float(row["weight"]),
                inference_version=row["inference_version"],
                observed_at=row["observed_at"],
            )
        )
    return tuple(signals)


def persist_inferred_signals(
    connection: sqlite3.Connection,
    user_id: str,
    signals: Sequence[InferredInterestSignal],
) -> None:
    connection.execute("DELETE FROM github_inferred_signals WHERE user_id = ?", (user_id,))
    connection.executemany(
        """
        INSERT INTO github_inferred_signals (
            user_id, repository, signal_type, topic_name, weight, inference_version, observed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                user_id,
                signal.repository,
                signal.signal_type,
                signal.topic_name,
                signal.weight,
                signal.inference_version,
                signal.observed_at,
            )
            for signal in signals
        ],
    )


def withdraw_persisted_repository(
    connection: sqlite3.Connection,
    user_id: str,
    repository: str,
) -> None:
    connection.execute(
        "DELETE FROM github_inferred_signals WHERE user_id = ? AND repository = ?",
        (user_id, repository.strip()),
    )


def reset_persisted_inferred_priors(connection: sqlite3.Connection, user_id: str) -> None:
    connection.execute("DELETE FROM github_inferred_signals WHERE user_id = ?", (user_id,))


def rebuild_inferred_priors_for_user(
    connection: sqlite3.Connection,
    user_id: str,
) -> InferredPriorState:
    selected = selected_repository_names(connection, user_id)
    selected_set = set(selected)
    stored = load_inferred_signals(connection, user_id)
    stale = any(signal.inference_version != INFERENCE_VERSION for signal in stored)
    orphaned = any(signal.repository not in selected_set for signal in stored)
    state = rebuild_inferred_priors(user_id, stored, selected_repositories=selected)
    if stale or orphaned or len(state.signals) != len(stored):
        persist_inferred_signals(connection, user_id, state.signals)
    return state


def inspect_inferred_priors_for_user(
    connection: sqlite3.Connection,
    user_id: str,
) -> InferredPriorState:
    return rebuild_inferred_priors_for_user(connection, user_id)


def reset_inferred_priors_for_user(
    connection: sqlite3.Connection,
    user_id: str,
) -> InferredPriorState:
    reset_persisted_inferred_priors(connection, user_id)
    return reset_inferred_priors(user_id)
