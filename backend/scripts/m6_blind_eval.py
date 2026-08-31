"""Evaluation-only M6 #171 one-shot blind adapter.

Production scoring never imports this module. Blind label files are opened
only here and in the CLI wrapper. Ranking / capacity / relation code is
called as frozen production, not modified.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from app.evaluation.m2_validation_metrics import (
    BOOTSTRAP_REPLICATES,
    BOOTSTRAP_SEED,
    LABEL_SOURCE,
    SEGMENT_DIMENSIONS,
    TOKEN_RE,
    _bootstrap_bundle,
    _failure_taxonomy,
    _item_kind,
    _ItemMetadata,
    _judgment_to_personalization,
    _metric_bundle,
    _product_name,
    _profile_to_user,
    _segment_metrics,
)
from app.evaluation.personalization_gold import PersonalizationGoldCorpus, PersonalizationItem
from app.evaluation.real_world_validation import (
    CONTRACT_VERSION,
    DATASET_VERSION,
    ValidationCorpus,
    coverage_inventory,
    load_real_world_validation,
)
from app.services.multiobjective_ranker import (
    RANKING_POLICY_VERSION,
    rank_personalization_corpus,
)
from app.services.ranking_capacity import CAPACITY_POLICY_VERSION
from app.services.relation import RELATION_FEATURE_VERSION

FROZEN_PRODUCTION_SHA = "b1befc9ee4ab04eefe64820ca27332438f8946ce"
REPORT_VERSION = "m6-oneshot-blind-aggregate-v1"
TOP3_FAMILIES = (
    "package_release_manager",
    "rust_compiler_contributor",
    "javascript_tooling_maintainer",
)
METRICS_VERSION = "m6-oneshot-blind-scoring-v1"


def load_m6_blind_holdout(corpus_dir: Path) -> ValidationCorpus:
    """Open the reserved blind split only. Not a production-scoring loader."""
    root = Path(corpus_dir)
    if "blind" in root.parts and root.name != "v01":
        raise ValueError(f"unexpected corpus path for M6 blind evaluation: {root}")
    return load_real_world_validation(root, splits=("blind",))


def build_blind_personalization_corpus(
    corpus: ValidationCorpus,
) -> tuple[PersonalizationGoldCorpus, dict[str, _ItemMetadata]]:
    """Adapt holdout records to the frozen ranker contract.

    Same real-event item construction as production scoring, but this helper
    is evaluation-only and therefore accepts split=blind.
    """
    if any(row.split != "blind" for row in corpus.profiles):
        raise ValueError("M6 one-shot blind adapter must receive only blind profiles")
    if any(row.split != "blind" for row in corpus.events):
        raise ValueError("M6 one-shot blind adapter must receive only blind events")
    if any(row.split != "blind" for row in corpus.judgments):
        raise ValueError("M6 one-shot blind adapter must receive only blind judgments")

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


def evaluate_m6_oneshot_blind(
    corpus: ValidationCorpus,
    *,
    repository_sha: str = FROZEN_PRODUCTION_SHA,
    bootstrap_replicates: int = BOOTSTRAP_REPLICATES,
    bootstrap_seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """Score the frozen production ranker on the reserved blind holdout once."""
    if repository_sha != FROZEN_PRODUCTION_SHA:
        raise ValueError(
            f"M6 one-shot blind must evaluate frozen SHA {FROZEN_PRODUCTION_SHA}, "
            f"got {repository_sha}"
        )
    adapted, metadata = build_blind_personalization_corpus(corpus)
    known_before = {
        (row.profile_id, row.event_id): row.known_before for row in corpus.judgments
    }
    predicted = rank_personalization_corpus(adapted)
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
    inventory = coverage_inventory(corpus)
    persona_families = sorted({user.profile.occupation for user in adapted.users})
    top3 = {}
    for family in TOP3_FAMILIES:
        family_segment = segments.get("persona_family", {}).get(family)
        sample_count = 0
        if family_segment is not None:
            sample_count = int(family_segment["at_10"]["sample_count"] or 0)
        top3[family] = {
            "present_in_holdout_profiles": family in persona_families,
            "scored": sample_count > 0,
            "at_10": None if family_segment is None else family_segment["at_10"],
        }
    scored_judgments = len(adapted.judgments)
    aggregate_status = "available" if scored_judgments else "not_scorable"
    return {
        "report_version": REPORT_VERSION,
        "status": "oneshot_blind_recorded",
        "aggregate_status": aggregate_status,
        "dataset_version": DATASET_VERSION,
        "contract_version": CONTRACT_VERSION,
        "metrics_version": METRICS_VERSION,
        "label_source": LABEL_SOURCE,
        "human_gold": False,
        "blind_read": True,
        "blind_records_loaded": True,
        "oneshot": True,
        "retune": False,
        "production_code_unchanged": True,
        "repository_sha": repository_sha,
        "ranking_policy_version": RANKING_POLICY_VERSION,
        "capacity_policy_version": CAPACITY_POLICY_VERSION,
        "relation_feature_version": RELATION_FEATURE_VERSION,
        "production_ranking_contract": (
            "app.services.multiobjective_ranker.rank_personalization_corpus"
        ),
        "holdout": {
            "split": "blind",
            "events": inventory["events"],
            "real_events": inventory["real_events"],
            "profiles": inventory["profiles"],
            "judgments": inventory["judgments"],
            "scored_real_events": len(adapted.items),
            "scored_judgments": len(adapted.judgments),
            "persona_families": persona_families,
        },
        "sample": {
            "profile_count": len(adapted.users),
            "real_event_count": len(adapted.items),
            "judgment_count": len(adapted.judgments),
            "persona_family_count": len(persona_families),
        },
        "headline": headline,
        "segments": segments,
        "uncertainty": {
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
                    for value in segments.get(dimension, {})
                }
                for dimension in SEGMENT_DIMENSIONS
            },
        },
        "failure_taxonomy": failure_taxonomy,
        "stage_attribution": failure_taxonomy["stage_attribution"],
        "top3_persona_families": top3,
        "notes": [
            "One-shot blind aggregate on frozen production SHA "
            f"{FROZEN_PRODUCTION_SHA}.",
            "Capacity policy remains capacity-policy-v1. Ranker weights unchanged.",
            "Production scoring still never opens blind files.",
            "AI-silver labels are not Human Gold.",
            "Do not retune ranking, capacity, or relation against this holdout.",
            "Holdout inventory is thin versus the M2 10k-judgment floor; record and stop.",
            (
                "The reserved blind split has one judgment, and the frozen real-event "
                "item construction scored zero judgments. Headline metrics are null. "
                "This is recorded, not retuned."
            ),
        ],
    }
