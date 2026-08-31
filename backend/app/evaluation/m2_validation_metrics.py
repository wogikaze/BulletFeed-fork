"""Production-scoring metrics for the M2 real-world validation corpus.

This module adapts the M2 corpus records to the existing production ranking
contract and scores the resulting rankings without opening blind records.
Labels remain AI-silver evaluation data; this module never rewrites them.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.evaluation.personalization_gold import (
    PersonalizationGoldCorpus,
    PersonalizationItem,
    PersonalizationJudgment,
    PersonalizationUser,
    PriorFeedbackRecord,
    RepositoryRecord,
    TopicRecord,
)
from app.evaluation.personalization_gold import (
    ProfileRecord as PersonalizationProfile,
)
from app.evaluation.ranking_benchmark import rank_user_items
from app.evaluation.real_world_validation import ValidationCorpus

METRICS_VERSION = "m2-production-scoring-v1"
LABEL_SOURCE = "AI-silver"
BOOTSTRAP_REPLICATES = 200
BOOTSTRAP_SEED = 20260830
IMPORTANT_MIN = 2
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9+._-]*", re.IGNORECASE)
SEGMENT_DIMENSIONS = (
    "cohort",
    "persona_family",
    "language",
    "source_family",
    "information_type",
)


@dataclass(frozen=True)
class _ItemMetadata:
    language: str
    source_family: str
    information_type: str


@dataclass(frozen=True)
class _MetricRow:
    user_id: str
    persona_family: str
    precision: float
    recall: float
    ndcg: float
    redundancy: float
    important_unknown_recall: float
    unknown_but_hidden_rate: float
    known_but_reshown_rate: float
    judgment_count: int


def build_personalization_corpus(
    corpus: ValidationCorpus,
) -> tuple[PersonalizationGoldCorpus, dict[str, _ItemMetadata]]:
    """Adapt production-scoring M2 records to the shared ranking contract."""
    if any(row.split == "blind" for row in corpus.profiles):
        raise ValueError("M2 production scoring must not include blind profiles")
    if any(row.split == "blind" for row in corpus.events):
        raise ValueError("M2 production scoring must not include blind events")
    if any(row.split == "blind" for row in corpus.judgments):
        raise ValueError("M2 production scoring must not include blind judgments")

    real_events = {row.event_id: row for row in corpus.events if row.is_real_event}
    sources_by_event: dict[str, list[Any]] = defaultdict(list)
    for source in corpus.sources:
        if source.event_id in real_events and source.source_role == "event_page":
            sources_by_event[source.event_id].append(source)

    users = tuple(_profile_to_user(profile) for profile in corpus.profiles)
    items: list[PersonalizationItem] = []
    metadata: dict[str, _ItemMetadata] = {}
    for event_id, event in sorted(real_events.items()):
        sources = sorted(sources_by_event.get(event_id, ()), key=lambda row: row.source_id)
        if not sources:
            continue
        source = sources[0]
        items.append(
            PersonalizationItem(
                item_id=event.event_id,
                split=event.split,
                title=event.title,
                summary=source.normalized_evidence,
                source_family=source.source_family,
                publisher=source.publisher,
                url=source.canonical_url,
                product=_product_name(source.publisher, event.title),
                kind=_item_kind(event.information_type),
                redundancy_group=event.redundancy_group,
                tokens=tuple(
                    sorted(
                        TOKEN_RE.findall(
                            f"{event.title} {source.publisher} {source.normalized_evidence}"
                        )
                    )
                ),
                lexical_traps_for=(),
                adjacent_products=(),
                ambiguous_for=(),
                occurred_at=getattr(event, "occurred_at", None),
            )
        )
        metadata[event.event_id] = _ItemMetadata(
            language=event.language,
            source_family=source.source_family,
            information_type=event.information_type,
        )

    item_ids = {item.item_id for item in items}
    profile_ids = {profile.profile_id for profile in corpus.profiles}
    judgments = tuple(
        _judgment_to_personalization(
            row,
            redundancy_group=real_events[row.event_id].redundancy_group,
        )
        for row in corpus.judgments
        if row.profile_id in profile_ids and row.event_id in item_ids
    )
    return (
        PersonalizationGoldCorpus(
            dataset_version=corpus.manifest.dataset_version,
            label_protocol_version=corpus.manifest.label_protocol_version,
            users=users,
            items=tuple(items),
            judgments=judgments,
        ),
        metadata,
    )


def evaluate_m2_production_scoring(
    corpus: ValidationCorpus,
    *,
    bootstrap_replicates: int = BOOTSTRAP_REPLICATES,
    bootstrap_seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """Rank pilot/dev M2 events with production logic and return segmented metrics."""
    adapted, metadata = build_personalization_corpus(corpus)
    known_before = {
        (row.profile_id, row.event_id): row.known_before
        for row in corpus.judgments
    }
    items = adapted.item_by_id()
    predicted = {
        user.user_id: rank_user_items(
            user,
            [
                items[judgment.item_id]
                for judgment in adapted.judgments_for_user(user.user_id)
            ],
        )
        for user in adapted.users
    }
    headline = {
        "include_ambiguous": _metric_bundle(
            adapted,
            predicted,
            metadata,
            known_before,
            drop_ambiguous=False,
        ),
        "exclude_ambiguous": _metric_bundle(
            adapted,
            predicted,
            metadata,
            known_before,
            drop_ambiguous=True,
        ),
    }
    segments = _segment_metrics(adapted, predicted, metadata, known_before)
    failure_taxonomy = _failure_taxonomy(adapted, predicted, metadata, known_before)
    uncertainty = {
        "method": "persona-family-cluster-bootstrap-percentile",
        "cluster_unit": "persona_family",
        "replicates": bootstrap_replicates,
        "seed": bootstrap_seed,
        "headline": _bootstrap_bundle(
            adapted,
            predicted,
            metadata,
            known_before,
            drop_ambiguous=False,
            replicates=bootstrap_replicates,
            seed=bootstrap_seed,
        ),
        "segments": {
            dimension: {
                value: _bootstrap_bundle(
                    adapted,
                    predicted,
                    metadata,
                    known_before,
                    drop_ambiguous=False,
                    dimension=dimension,
                    value=value,
                    replicates=bootstrap_replicates,
                    seed=bootstrap_seed,
                )
                for value in _segment_values(dimension, adapted, metadata)
            }
            for dimension in SEGMENT_DIMENSIONS
        },
    }
    return {
        "metrics_version": METRICS_VERSION,
        "label_source": LABEL_SOURCE,
        "human_gold": False,
        "blind_records_loaded": False,
        "production_ranking_contract": "app.evaluation.ranking_benchmark.rank_user_items",
        "sample": {
            "profile_count": len(adapted.users),
            "real_event_count": len(adapted.items),
            "judgment_count": len(adapted.judgments),
            "persona_family_count": len(
                {user.profile.occupation for user in adapted.users}
            ),
        },
        "headline": headline,
        "segments": segments,
        "uncertainty": uncertainty,
        "failure_taxonomy": failure_taxonomy,
        "stage_attribution": failure_taxonomy["stage_attribution"],
    }


def _profile_to_user(profile) -> PersonalizationUser:
    return PersonalizationUser(
        user_id=profile.profile_id,
        split=profile.split,
        kind=profile.cohort,
        profile=PersonalizationProfile(
            occupation=profile.persona_template,
            interests=profile.explicit_interests,
            region=profile.language_focus,
        ),
        topics=tuple(
            TopicRecord(name=interest, type="technology", priority="high")
            for interest in profile.explicit_interests
        ),
        repositories=tuple(
            RepositoryRecord(full_name=repository)
            for repository in profile.selected_repositories
        ),
        prior_feedback=tuple(
            PriorFeedbackRecord(summary=feedback, feedback="important")
            for feedback in profile.prior_feedback
        ),
        products=tuple(profile.followed_products),
        adjacent_products=(),
        watches_security=profile.security_sensitivity == "high",
    )


def _judgment_to_personalization(judgment, *, redundancy_group: str) -> PersonalizationJudgment:
    return PersonalizationJudgment(
        judgment_id=judgment.judgment_id,
        user_id=judgment.profile_id,
        item_id=judgment.event_id,
        relevance=judgment.relevance,
        importance_to_user=judgment.importance_to_user,
        should_surface=judgment.should_surface,
        redundancy_group=redundancy_group,
        rationale=judgment.rationale,
        provenance=judgment.provenance,
        ambiguous=judgment.ambiguous,
        hard_negative=judgment.stratum in {"hard_negative", "lexical_trap", "unrelated"},
        label_protocol_version=judgment.label_protocol_version,
        dataset_version=judgment.dataset_version,
        split=judgment.split,
    )


def _product_name(publisher: str, title: str) -> str:
    publisher_name = publisher.rsplit("/", 1)[-1].strip()
    return publisher_name or title.split(" ", 1)[0]


def _item_kind(information_type: str) -> str:
    if information_type == "incident":
        return "outage"
    if information_type == "security":
        return "advisory"
    if information_type == "release":
        return "release"
    return "news"


def _metric_rows(
    corpus: PersonalizationGoldCorpus,
    predicted: Mapping[str, Sequence[str]],
    metadata: Mapping[str, _ItemMetadata],
    known_before: Mapping[tuple[str, str], bool],
    *,
    k: int,
    drop_ambiguous: bool,
    dimension: str | None = None,
    value: str | None = None,
) -> list[_MetricRow]:
    if k < 1:
        raise ValueError("k must be >= 1")
    items = corpus.item_by_id()
    rows: list[_MetricRow] = []
    for user in corpus.users:
        selected = [
            judgment
            for judgment in corpus.judgments_for_user(user.user_id)
            if not (drop_ambiguous and judgment.ambiguous)
            and (
                dimension is None
                or _matches_segment(user, judgment, metadata, dimension, value)
            )
        ]
        if not selected:
            continue
        by_item = {judgment.item_id: judgment for judgment in selected}
        ranking = [item_id for item_id in predicted.get(user.user_id, ()) if item_id in by_item]
        ranking.extend(
            judgment.item_id
            for judgment in selected
            if judgment.item_id not in ranking
        )
        top = ranking[:k]
        relevant = {judgment.item_id for judgment in selected if judgment.should_surface}
        hits = sum(item_id in relevant for item_id in top)
        important_unknown = {
            judgment.item_id
            for judgment in selected
            if judgment.should_surface
            and judgment.importance_to_user >= IMPORTANT_MIN
            and not known_before.get((user.user_id, judgment.item_id), False)
        }
        unknown_relevant = {
            judgment.item_id
            for judgment in selected
            if judgment.should_surface
            and not known_before.get((user.user_id, judgment.item_id), False)
        }
        known = {
            judgment.item_id
            for judgment in selected
            if known_before.get((user.user_id, judgment.item_id), False)
        }
        gains = [by_item[item_id].relevance for item_id in top]
        ideal = sorted((judgment.relevance for judgment in selected), reverse=True)[:k]
        seen_groups: set[str] = set()
        redundant = 0
        for item_id in top:
            group = items[item_id].redundancy_group
            if group in seen_groups:
                redundant += 1
            seen_groups.add(group)
        rows.append(
            _MetricRow(
                user_id=user.user_id,
                persona_family=user.profile.occupation,
                precision=hits / k,
                recall=hits / len(relevant) if relevant else 1.0,
                ndcg=_ndcg(gains, ideal),
                redundancy=redundant / k,
                important_unknown_recall=(
                    sum(item_id in top for item_id in important_unknown)
                    / len(important_unknown)
                    if important_unknown
                    else 1.0
                ),
                unknown_but_hidden_rate=(
                    sum(item_id not in top for item_id in unknown_relevant)
                    / len(unknown_relevant)
                    if unknown_relevant
                    else 0.0
                ),
                known_but_reshown_rate=(
                    sum(item_id in top for item_id in known) / len(known)
                    if known
                    else 0.0
                ),
                judgment_count=len(selected),
            )
        )
    return rows


def _failure_taxonomy(
    corpus: PersonalizationGoldCorpus,
    predicted: Mapping[str, Sequence[str]],
    metadata: Mapping[str, _ItemMetadata],
    known_before: Mapping[tuple[str, str], bool],
) -> dict[str, Any]:
    categories = (
        "important_unknown_missed",
        "unknown_but_hidden",
        "known_but_reshown",
    )
    dimension_names = ("persona_family", "cohort", "language", "source_family", "information_type")
    by_dimension: dict[str, dict[str, Counter[str]]] = {
        category: {dimension: Counter() for dimension in dimension_names}
        for category in categories
    }
    failure_counts: Counter[str] = Counter()
    representative: list[dict[str, Any]] = []
    for user in corpus.users:
        ranked = set(predicted.get(user.user_id, ())[:10])
        for judgment in corpus.judgments_for_user(user.user_id):
            is_known = known_before.get((user.user_id, judgment.item_id), False)
            if judgment.should_surface and not is_known and judgment.item_id not in ranked:
                category = (
                    "important_unknown_missed"
                    if judgment.importance_to_user >= IMPORTANT_MIN
                    else "unknown_but_hidden"
                )
            elif is_known and judgment.item_id in ranked:
                category = "known_but_reshown"
            else:
                continue
            failure_counts[category] += 1
            item = metadata[judgment.item_id]
            values = {
                "persona_family": user.profile.occupation,
                "cohort": user.kind,
                "language": item.language,
                "source_family": item.source_family,
                "information_type": item.information_type,
            }
            for dimension, value in values.items():
                by_dimension[category][dimension][value] += 1

    for category in categories:
        for dimension in dimension_names:
            for value, count in by_dimension[category][dimension].items():
                representative.append(
                    {
                        "failure": category,
                        "dimension": dimension,
                        "value": value,
                        "count": count,
                    }
                )
    representative.sort(
        key=lambda row: (-int(row["count"]), row["failure"], row["dimension"], row["value"])
    )
    stage_counts = {
        "ranking": failure_counts["important_unknown_missed"]
        + failure_counts["unknown_but_hidden"]
        + failure_counts["known_but_reshown"]
    }
    return {
        "status": "available",
        "covered_stage": "ranking",
        "failure_counts": dict(sorted(failure_counts.items())),
        "by_dimension": {
            category: {
                dimension: dict(sorted(counts.items()))
                for dimension, counts in dimensions.items()
            }
            for category, dimensions in by_dimension.items()
        },
        "representative_clusters": representative[:50],
        "representative_cluster_minimum": 20,
        "stage_attribution": {
            "status": "partial",
            "earliest_stage_for_recorded_failures": "ranking",
            "failure_count": stage_counts["ranking"],
            "by_stage": stage_counts,
            "uncovered_stages": ["acquisition", "projection", "evidence"],
            "note": (
                "These are misses in the production ranking replay. Acquisition, projection, "
                "and evidence failures require full journey traces and are not inferred here."
            ),
        },
    }


def _metric_bundle(
    corpus: PersonalizationGoldCorpus,
    predicted: Mapping[str, Sequence[str]],
    metadata: Mapping[str, _ItemMetadata],
    known_before: Mapping[tuple[str, str], bool],
    *,
    drop_ambiguous: bool,
    dimension: str | None = None,
    value: str | None = None,
) -> dict[str, dict[str, Any]]:
    return {
        f"at_{k}": _summarize(
            _metric_rows(
                corpus,
                predicted,
                metadata,
                known_before,
                k=k,
                drop_ambiguous=drop_ambiguous,
                dimension=dimension,
                value=value,
            ),
            k=k,
        )
        for k in (5, 10)
    }


def _matches_segment(
    user: PersonalizationUser,
    judgment: PersonalizationJudgment,
    metadata: Mapping[str, _ItemMetadata],
    dimension: str,
    value: str | None,
) -> bool:
    if value is None:
        return True
    if dimension == "cohort":
        return user.kind == value
    if dimension == "persona_family":
        return user.profile.occupation == value
    item = metadata.get(judgment.item_id)
    if item is None:
        return False
    return getattr(item, dimension) == value


def _segment_values(
    dimension: str,
    corpus: PersonalizationGoldCorpus,
    metadata: Mapping[str, _ItemMetadata],
) -> tuple[str, ...]:
    if dimension == "cohort":
        return tuple(sorted({user.kind for user in corpus.users}))
    if dimension == "persona_family":
        return tuple(sorted({user.profile.occupation for user in corpus.users}))
    return tuple(sorted({getattr(item, dimension) for item in metadata.values()}))


def _segment_metrics(
    corpus: PersonalizationGoldCorpus,
    predicted: Mapping[str, Sequence[str]],
    metadata: Mapping[str, _ItemMetadata],
    known_before: Mapping[tuple[str, str], bool],
) -> dict[str, dict[str, dict[str, Any]]]:
    return {
        dimension: {
            value: _metric_bundle(
                corpus,
                predicted,
                metadata,
                known_before,
                drop_ambiguous=False,
                dimension=dimension,
                value=value,
            )
            for value in _segment_values(dimension, corpus, metadata)
        }
        for dimension in SEGMENT_DIMENSIONS
    }


def _summarize(rows: Sequence[_MetricRow], *, k: int) -> dict[str, Any]:
    if not rows:
        return {
            "sample_count": 0,
            "judgment_count": 0,
            f"precision_at_{k}": None,
            f"recall_at_{k}": None,
            f"ndcg_at_{k}": None,
            f"redundancy_at_{k}": None,
            f"important_unknown_recall_at_{k}": None,
            "unknown_but_hidden_rate": None,
            "known_but_reshown_rate": None,
        }
    return {
        "sample_count": len(rows),
        "judgment_count": sum(row.judgment_count for row in rows),
        f"precision_at_{k}": _mean(row.precision for row in rows),
        f"recall_at_{k}": _mean(row.recall for row in rows),
        f"ndcg_at_{k}": _mean(row.ndcg for row in rows),
        f"redundancy_at_{k}": _mean(row.redundancy for row in rows),
        f"important_unknown_recall_at_{k}": _mean(
            row.important_unknown_recall for row in rows
        ),
        "unknown_but_hidden_rate": _mean(row.unknown_but_hidden_rate for row in rows),
        "known_but_reshown_rate": _mean(row.known_but_reshown_rate for row in rows),
    }


def _bootstrap_bundle(
    corpus: PersonalizationGoldCorpus,
    predicted: Mapping[str, Sequence[str]],
    metadata: Mapping[str, _ItemMetadata],
    known_before: Mapping[tuple[str, str], bool],
    *,
    drop_ambiguous: bool,
    dimension: str | None = None,
    value: str | None = None,
    replicates: int,
    seed: int,
) -> dict[str, dict[str, Any]]:
    return {
        f"at_{k}": _bootstrap_for_rows(
            _metric_rows(
                corpus,
                predicted,
                metadata,
                known_before,
                k=k,
                drop_ambiguous=drop_ambiguous,
                dimension=dimension,
                value=value,
            ),
            k=k,
            replicates=replicates,
            seed=seed,
        )
        for k in (5, 10)
    }


def _bootstrap_for_rows(
    rows: Sequence[_MetricRow],
    *,
    k: int,
    replicates: int,
    seed: int,
) -> dict[str, Any]:
    if replicates < 1:
        raise ValueError("bootstrap replicates must be >= 1")
    if not rows:
        return {"status": "not_available", "sample_count": 0}
    clusters: dict[str, list[_MetricRow]] = defaultdict(list)
    for row in rows:
        clusters[row.persona_family].append(row)
    if len(clusters) < 2:
        return {
            "status": "not_available",
            "sample_count": len(rows),
            "cluster_count": len(clusters),
            "reason": "at least two persona-family clusters are required",
        }
    cluster_names = tuple(sorted(clusters))
    values: dict[str, list[float]] = defaultdict(list)
    for replicate in range(replicates):
        sampled = [
            row
            for draw in range(len(cluster_names))
            for cluster_name in (
                cluster_names[_bootstrap_index(seed, replicate, draw, len(cluster_names))],
            )
            for row in clusters[cluster_name]
        ]
        values[f"precision_at_{k}"].append(_mean(row.precision for row in sampled))
        values[f"recall_at_{k}"].append(_mean(row.recall for row in sampled))
        values[f"ndcg_at_{k}"].append(_mean(row.ndcg for row in sampled))
        values[f"redundancy_at_{k}"].append(_mean(row.redundancy for row in sampled))
        values[f"important_unknown_recall_at_{k}"].append(
            _mean(row.important_unknown_recall for row in sampled)
        )
    return {
        "status": "available",
        "sample_count": len(rows),
        "cluster_count": len(clusters),
        "ci95": {
            key: list(_percentile_interval(samples))
            for key, samples in sorted(values.items())
        },
    }


def _bootstrap_index(seed: int, replicate: int, draw: int, cluster_count: int) -> int:
    material = f"{seed}:{replicate}:{draw}".encode()
    digest = hashlib.sha256(material).digest()
    return int.from_bytes(digest[:8], "big") % cluster_count


def _mean(values: Sequence[float] | Any) -> float:
    values = tuple(values)
    return round(sum(values) / len(values), 6) if values else 0.0


def _percentile_interval(values: Sequence[float]) -> tuple[float, float]:
    ordered = sorted(values)
    lower = ordered[max(0, math.floor((len(ordered) - 1) * 0.025))]
    upper = ordered[min(len(ordered) - 1, math.ceil((len(ordered) - 1) * 0.975))]
    return round(lower, 6), round(upper, 6)


def _ndcg(gains: Sequence[int], ideal: Sequence[int]) -> float:
    ideal_score = _dcg(ideal)
    if ideal_score == 0:
        return 0.0
    return round(_dcg(gains) / ideal_score, 6)


def _dcg(gains: Sequence[int]) -> float:
    return sum((2**gain - 1) / math.log2(index + 2) for index, gain in enumerate(gains))
