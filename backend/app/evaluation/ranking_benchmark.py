"""Short-session product ranking benchmark over Rec-01 (#37) gold.

This module scores the existing feed-ordering axes against fixed user×item
labels. It does not rewrite Gold judgments and does not change ranking
algorithms to chase those labels. Blind labels are evaluation-only.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from app.evaluation.personalization_gold import (
    PersonalizationGoldCorpus,
    PersonalizationItem,
    PersonalizationJudgment,
    PersonalizationMetrics,
    PersonalizationUser,
    evaluate_personalization,
    load_personalization_gold,
)
from app.services.cold_start_policy import COLD_START_POLICY_VERSION, classify_personalization_user
from app.services.ranking import evaluate_importance
from app.services.relation import RELATION_FEATURE_VERSION, evaluate_relation_from_state
from app.services.user_interest import semantic_match, state_from_personalization_user

BENCHMARK_VERSION = "ranking-benchmark-v0.1"
RANKING_CONTRACT_VERSION = "feed-order-v4"
LABEL_SOURCE = "personalization-v0.1"
IMPORTANT_MIN = 2

# FeedStore ORDER BY knownness_rank DESC, importance_rank DESC, relation_rank DESC,
# personalization_rank DESC. Short-session users have no knowledge evidence.
_IMPORTANCE_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}
_RELATION_RANK = {"direct": 3, "adjacent": 2, "reference": 1}
UNKNOWN_KNOWNNESS_RANK = 2

# Pilot-only release floors. Blind metrics are reported, never used to set these.
DEFAULT_REGRESSION_TOLERANCE = 0.05


@dataclass(frozen=True)
class RankingSnapshot:
    benchmark_version: str
    dataset_version: str
    ranking_contract_version: str
    relation_feature_version: str
    cold_start_policy_version: str
    split: str
    user_ids: tuple[str, ...]
    item_ids: tuple[str, ...]
    observation_ids: tuple[str, ...]
    user_kind_counts: dict[str, int]
    fingerprint: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AxisScores:
    item_id: str
    knownness_rank: int
    importance_rank: int
    relation_rank: int
    personalization_rank: int
    interest_score: float
    importance_level: str
    relation_level: str


@dataclass(frozen=True)
class SessionSliceMetrics:
    k: int
    user_count: int
    precision_at_k: float
    recall_at_k: float
    ndcg_at_k: float
    redundancy_at_k: float
    useful_in_top_k: float
    important_recall_at_k: float
    irrelevant_card_rate: float
    cards_to_first_useful: float
    important_item_missed_rate: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AxisDiagnostic:
    axis: str
    mean_value: float
    precision_at_5: float
    ndcg_at_10: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RankingBenchmarkReport:
    benchmark_version: str
    dataset_version: str
    ranking_contract_version: str
    split: str
    snapshot: RankingSnapshot
    at_5: SessionSliceMetrics
    at_10: SessionSliceMetrics
    by_kind: dict[str, dict[str, SessionSliceMetrics]]
    axes: tuple[AxisDiagnostic, ...]
    label_source: str = LABEL_SOURCE
    labels_rewritten: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "benchmark_version": self.benchmark_version,
            "dataset_version": self.dataset_version,
            "ranking_contract_version": self.ranking_contract_version,
            "split": self.split,
            "label_source": self.label_source,
            "labels_rewritten": self.labels_rewritten,
            "snapshot": self.snapshot.as_dict(),
            "at_5": self.at_5.as_dict(),
            "at_10": self.at_10.as_dict(),
            "by_kind": {
                kind: {key: metrics.as_dict() for key, metrics in slices.items()}
                for kind, slices in self.by_kind.items()
            },
            "axes": [axis.as_dict() for axis in self.axes],
        }


def load_ranking_gold(corpus_dir: Path) -> PersonalizationGoldCorpus:
    """Load Rec-01 gold as-is. Callers must not persist mutated labels."""
    return load_personalization_gold(corpus_dir)


def build_ranking_snapshot(corpus: PersonalizationGoldCorpus, *, split: str) -> RankingSnapshot:
    scoped = corpus.for_split(split)
    user_ids = tuple(user.user_id for user in scoped.users)
    item_ids = tuple(item.item_id for item in scoped.items)
    observation_ids = tuple(f"obs:{item_id}" for item_id in item_ids)
    counts: dict[str, int] = {}
    for user in scoped.users:
        counts[user.kind] = counts.get(user.kind, 0) + 1
    payload = "|".join(
        (
            BENCHMARK_VERSION,
            RANKING_CONTRACT_VERSION,
            split,
            ",".join(user_ids),
            ",".join(item_ids),
            ",".join(observation_ids),
        )
    )
    fingerprint = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return RankingSnapshot(
        benchmark_version=BENCHMARK_VERSION,
        dataset_version=scoped.dataset_version,
        ranking_contract_version=RANKING_CONTRACT_VERSION,
        relation_feature_version=RELATION_FEATURE_VERSION,
        cold_start_policy_version=COLD_START_POLICY_VERSION,
        split=split,
        user_ids=user_ids,
        item_ids=item_ids,
        observation_ids=observation_ids,
        user_kind_counts=counts,
        fingerprint=fingerprint,
    )


def interest_state_for(user: PersonalizationUser):
    return state_from_personalization_user(
        user.user_id,
        occupation=user.profile.occupation,
        interests=user.profile.interests,
        topics=tuple((topic.name, topic.priority) for topic in user.topics),
        repositories=tuple((repo.full_name, repo.language) for repo in user.repositories),
        prior_feedback=tuple((row.summary, row.feedback) for row in user.prior_feedback),
    )


def score_item_axes(user: PersonalizationUser, item: PersonalizationItem, state) -> AxisScores:
    relation = evaluate_relation_from_state(
        state,
        source_type=item.source_family,
        source_key=item.publisher,
        event_title=item.title,
        event_summary=item.summary,
    )
    importance = evaluate_importance(
        source_type=item.source_family,
        delta_type=_delta_type_for(item),
    )
    interest = semantic_match(state, f"{item.title} {item.summary} {' '.join(item.tokens)}")
    return AxisScores(
        item_id=item.item_id,
        knownness_rank=UNKNOWN_KNOWNNESS_RANK,
        importance_rank=_IMPORTANCE_RANK[importance.level],
        relation_rank=_RELATION_RANK.get(relation.level, 1),
        personalization_rank=relation.personalization_rank,
        interest_score=interest.score,
        importance_level=importance.level,
        relation_level=relation.level,
    )


def feed_sort_key(axis: AxisScores) -> tuple[int, int, int, int, str]:
    """Same axis order as FeedStore v4. Gold item_id is the stable tie-break."""
    return (
        axis.knownness_rank,
        axis.importance_rank,
        axis.relation_rank,
        axis.personalization_rank,
        axis.item_id,
    )


def rank_user_items(
    user: PersonalizationUser,
    items: Sequence[PersonalizationItem],
    *,
    state=None,
) -> list[str]:
    interest = state if state is not None else interest_state_for(user)
    scored = [score_item_axes(user, item, interest) for item in items]
    scored.sort(key=feed_sort_key, reverse=True)
    return [axis.item_id for axis in scored]


def product_rankings(corpus: PersonalizationGoldCorpus) -> dict[str, list[str]]:
    items = corpus.item_by_id()
    rankings: dict[str, list[str]] = {}
    for user in corpus.users:
        judged = [items[row.item_id] for row in corpus.judgments_for_user(user.user_id)]
        rankings[user.user_id] = rank_user_items(user, judged)
    return rankings


def evaluate_ranking_benchmark(
    corpus: PersonalizationGoldCorpus,
    *,
    split: Literal["pilot", "blind"],
    predicted: Mapping[str, Sequence[str]] | None = None,
) -> RankingBenchmarkReport:
    scoped = corpus.for_split(split)
    rankings = dict(predicted) if predicted is not None else product_rankings(scoped)
    snapshot = build_ranking_snapshot(corpus, split=split)
    at_5 = _session_slice(scoped, rankings, k=5)
    at_10 = _session_slice(scoped, rankings, k=10)
    kinds = sorted({user.kind for user in scoped.users})
    by_kind = {
        kind: {
            "at_5": _session_slice(scoped, rankings, k=5, kinds={kind}),
            "at_10": _session_slice(scoped, rankings, k=10, kinds={kind}),
        }
        for kind in kinds
    }
    return RankingBenchmarkReport(
        benchmark_version=BENCHMARK_VERSION,
        dataset_version=scoped.dataset_version,
        ranking_contract_version=RANKING_CONTRACT_VERSION,
        split=split,
        snapshot=snapshot,
        at_5=at_5,
        at_10=at_10,
        by_kind=by_kind,
        axes=_axis_diagnostics(scoped, rankings),
    )


def ranking_regression_violations(
    current: RankingBenchmarkReport,
    baseline: Mapping[str, Any],
    *,
    tolerance: float = DEFAULT_REGRESSION_TOLERANCE,
) -> tuple[str, ...]:
    """Detect material regressions against a checked-in pilot baseline."""
    if current.split != "pilot":
        raise ValueError("regression floors may only be applied to the pilot split")
    violations: list[str] = []
    for key, higher_is_better in (
        ("precision_at_k", True),
        ("recall_at_k", True),
        ("ndcg_at_k", True),
    ):
        observed = getattr(current.at_5 if key == "precision_at_k" else current.at_10, key)
        expected = float(baseline["at_5" if key == "precision_at_k" else "at_10"][key])
        if higher_is_better and observed + tolerance < expected:
            violations.append(f"{key} {observed:.3f} dropped more than {tolerance:.3f} from {expected:.3f}")
        if not higher_is_better and observed - tolerance > expected:
            violations.append(f"{key} {observed:.3f} rose more than {tolerance:.3f} from {expected:.3f}")
    redundancy = current.at_10.redundancy_at_k
    baseline_redundancy = float(baseline["at_10"]["redundancy_at_k"])
    if redundancy - tolerance > baseline_redundancy:
        violations.append(
            f"redundancy_at_k {redundancy:.3f} rose more than {tolerance:.3f} from {baseline_redundancy:.3f}"
        )
    missed = current.at_10.important_item_missed_rate
    baseline_missed = float(baseline["at_10"]["important_item_missed_rate"])
    if missed - tolerance > baseline_missed:
        violations.append(
            "important_item_missed_rate "
            f"{missed:.3f} rose more than {tolerance:.3f} from {baseline_missed:.3f}"
        )
    return tuple(violations)


def require_ranking_regression_gate(
    current: RankingBenchmarkReport,
    baseline: Mapping[str, Any],
    *,
    tolerance: float = DEFAULT_REGRESSION_TOLERANCE,
) -> None:
    violations = ranking_regression_violations(current, baseline, tolerance=tolerance)
    if violations:
        raise AssertionError("ranking benchmark regression: " + "; ".join(violations))


def load_baseline_report(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("baseline report must be an object")
    return payload


def write_report(report: RankingBenchmarkReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def cohort_for(user: PersonalizationUser) -> str:
    return classify_personalization_user(
        topics=tuple(topic.name for topic in user.topics),
        repositories=tuple(repo.full_name for repo in user.repositories),
        profile_interests=user.profile.interests,
        prior_feedback=user.prior_feedback,
    )


def _delta_type_for(item: PersonalizationItem) -> str:
    text = f"{item.title} {item.summary}".casefold()
    if "correct" in text:
        return "correction"
    if item.kind == "outage":
        return "state_update"
    return "new_fact"


def _session_slice(
    corpus: PersonalizationGoldCorpus,
    predicted: Mapping[str, Sequence[str]],
    *,
    k: int,
    kinds: set[str] | None = None,
) -> SessionSliceMetrics:
    gold = evaluate_personalization(corpus, predicted, k=k)
    ranked_metrics = gold.include_ambiguous
    if kinds is not None:
        slice_name = next(iter(kinds))
        ranked_metrics = gold.slices.get(slice_name, ranked_metrics)
    users = [user for user in corpus.users if kinds is None or user.kind in kinds]
    useful_counts: list[float] = []
    important_recalls: list[float] = []
    first_useful: list[float] = []
    missed_rates: list[float] = []
    for user in users:
        judgments = corpus.judgments_for_user(user.user_id)
        ranking = list(predicted.get(user.user_id, ()))
        row = _per_user_session(judgments, ranking, k=k)
        useful_counts.append(row[0])
        important_recalls.append(row[1])
        first_useful.append(row[2])
        missed_rates.append(row[3])
    if not users:
        return SessionSliceMetrics(k, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    return SessionSliceMetrics(
        k=k,
        user_count=len(users),
        precision_at_k=ranked_metrics.precision_at_k,
        recall_at_k=ranked_metrics.recall_at_k,
        ndcg_at_k=ranked_metrics.ndcg_at_k,
        redundancy_at_k=ranked_metrics.redundancy_at_k,
        useful_in_top_k=sum(useful_counts) / len(useful_counts),
        important_recall_at_k=sum(important_recalls) / len(important_recalls),
        irrelevant_card_rate=ranked_metrics.irrelevant_item_rate,
        cards_to_first_useful=sum(first_useful) / len(first_useful),
        important_item_missed_rate=sum(missed_rates) / len(missed_rates),
    )


def _per_user_session(
    judgments: Sequence[PersonalizationJudgment],
    ranking: Sequence[str],
    *,
    k: int,
) -> tuple[float, float, float, float]:
    useful = {row.item_id for row in judgments if row.should_surface}
    important = {
        row.item_id
        for row in judgments
        if row.should_surface and row.importance_to_user >= IMPORTANT_MIN
    }
    top = list(ranking[:k])
    useful_hits = sum(1 for item_id in top if item_id in useful)
    important_hits = sum(1 for item_id in top if item_id in important)
    first = next((index for index, item_id in enumerate(ranking, start=1) if item_id in useful), k + 1)
    missed = (len(important - set(top)) / len(important)) if important else 0.0
    important_recall = (important_hits / len(important)) if important else 1.0
    return float(useful_hits), important_recall, float(first), missed


def _axis_diagnostics(
    corpus: PersonalizationGoldCorpus,
    predicted: Mapping[str, Sequence[str]],
) -> tuple[AxisDiagnostic, ...]:
    items = corpus.item_by_id()
    axis_values: dict[str, list[float]] = {
        "knownness_rank": [],
        "importance_rank": [],
        "relation_rank": [],
        "personalization_rank": [],
    }
    single_axis: dict[str, dict[str, list[str]]] = {
        "importance_rank": {},
        "relation_rank": {},
        "personalization_rank": {},
    }
    for user in corpus.users:
        state = interest_state_for(user)
        judged = [items[row.item_id] for row in corpus.judgments_for_user(user.user_id)]
        scored = [score_item_axes(user, item, state) for item in judged]
        for axis in scored:
            axis_values["knownness_rank"].append(axis.knownness_rank)
            axis_values["importance_rank"].append(axis.importance_rank)
            axis_values["relation_rank"].append(axis.relation_rank)
            axis_values["personalization_rank"].append(axis.personalization_rank)
        for name, key in (
            ("importance_rank", lambda row: (row.importance_rank, row.item_id)),
            ("relation_rank", lambda row: (row.relation_rank, row.item_id)),
            ("personalization_rank", lambda row: (row.personalization_rank, row.item_id)),
        ):
            ordered = sorted(scored, key=key, reverse=True)
            single_axis[name][user.user_id] = [row.item_id for row in ordered]
    diagnostics: list[AxisDiagnostic] = []
    for name, values in axis_values.items():
        mean = sum(values) / len(values) if values else 0.0
        if name == "knownness_rank":
            gold_at_5 = evaluate_personalization(corpus, predicted, k=5).include_ambiguous
            gold_at_10 = evaluate_personalization(corpus, predicted, k=10).include_ambiguous
            diagnostics.append(
                AxisDiagnostic(name, mean, gold_at_5.precision_at_k, gold_at_10.ndcg_at_k)
            )
            continue
        at_5 = evaluate_personalization(corpus, single_axis[name], k=5).include_ambiguous
        at_10 = evaluate_personalization(corpus, single_axis[name], k=10).include_ambiguous
        diagnostics.append(AxisDiagnostic(name, mean, at_5.precision_at_k, at_10.ndcg_at_k))
    return tuple(diagnostics)


def personalization_metrics_at(
    corpus: PersonalizationGoldCorpus,
    predicted: Mapping[str, Sequence[str]],
    *,
    k: int,
) -> PersonalizationMetrics:
    return evaluate_personalization(corpus, predicted, k=k).include_ambiguous
