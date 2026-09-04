"""Score source discovery against an independently acquired candidate artifact.

The artifact contains only acquisition output (URLs, families, concept ids and
provenance). It must not contain gold labels or expected URLs. Curated/builtin
source hints remain disabled while scoring.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.evaluation import source_discovery_quality as quality
from app.services.source_catalog import SourceKind
from app.services.source_discovery import DiscoveryHint, discover_sources_for_topics
from app.services.source_discovery_seeds import DiscoveryProvenance
from app.services.source_registry import SourceRegistry, canonicalize_url

INDEPENDENT_CANDIDATE_VERSION = "source-discovery-independent-candidates-v0.1"

_ALLOWED_PROVENANCE = frozenset(
    {
        DiscoveryProvenance.REPOSITORY_METADATA.value,
        DiscoveryProvenance.WEBSITE_FEED.value,
        DiscoveryProvenance.STATUSPAGE_LINK.value,
        DiscoveryProvenance.SITEMAP_LINK.value,
        DiscoveryProvenance.PACKAGE_HOMEPAGE.value,
        DiscoveryProvenance.EXTERNAL_INDEX.value,
    }
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IndependentCandidate(_StrictModel):
    url: str = Field(min_length=1)
    family: str = Field(min_length=1)
    concept_ids: list[str] = Field(min_length=1)
    provenance: str = Field(min_length=1)
    title: str = ""
    publisher_slug: str | None = None
    publisher_name: str | None = None
    homepage_url: str | None = None
    why: str = ""
    display_name: str = ""
    observed_via: str = Field(min_length=1)
    evidence_reference: str = Field(min_length=1)


class IndependentCandidateArtifact(_StrictModel):
    artifact_version: Literal["source-discovery-independent-candidates-v0.1"]
    acquisition_mode: Literal["recorded_external"]
    gold_read: Literal[False]
    collector_version: str = Field(min_length=1)
    items: list[IndependentCandidate] = Field(min_length=1)


def load_independent_candidate_artifact(path: Path) -> IndependentCandidateArtifact:
    artifact = IndependentCandidateArtifact.model_validate(
        json.loads(path.read_text(encoding="utf-8"))
    )
    validate_independent_candidate_artifact(artifact)
    return artifact


def validate_independent_candidate_artifact(artifact: IndependentCandidateArtifact) -> None:
    if artifact.artifact_version != INDEPENDENT_CANDIDATE_VERSION:
        raise ValueError(f"unsupported independent candidate version: {artifact.artifact_version}")
    seen: set[tuple[str, str, tuple[str, ...]]] = set()
    for item in artifact.items:
        if item.provenance not in _ALLOWED_PROVENANCE:
            raise ValueError(f"candidate provenance is not independent: {item.provenance}")
        try:
            SourceKind(item.family)
        except ValueError as exc:
            raise ValueError(f"candidate has unknown source family: {item.family}") from exc
        canonical = canonicalize_url(item.url)
        if canonical != item.url:
            raise ValueError(f"candidate URL is not canonicalized: {item.url}")
        concepts = tuple(dict.fromkeys(value.strip() for value in item.concept_ids if value.strip()))
        if not concepts or len(concepts) != len(item.concept_ids):
            raise ValueError("candidate concept_ids must be unique non-empty ids")
        identity = (item.family, canonical, concepts)
        if identity in seen:
            raise ValueError(f"duplicate independent candidate: {item.url}")
        seen.add(identity)


def independent_discovery_hints(
    artifact: IndependentCandidateArtifact,
) -> tuple[DiscoveryHint, ...]:
    validate_independent_candidate_artifact(artifact)
    return tuple(
        DiscoveryHint(
            url=item.url,
            provenance=item.provenance,
            family=SourceKind(item.family),
            concept_ids=tuple(item.concept_ids),
            title=item.title,
            publisher_slug=item.publisher_slug,
            publisher_name=item.publisher_name,
            homepage_url=item.homepage_url,
            why=item.why or f"Recorded independent acquisition via {item.observed_via}",
            display_name=item.display_name,
        )
        for item in artifact.items
    )


def evaluate_source_discovery_quality_with_independent_candidates(
    corpus: quality.SourceDiscoveryQualityCorpus,
    artifact: IndependentCandidateArtifact,
    *,
    registry: SourceRegistry | None = None,
    source_sha: str | None = None,
) -> quality.SourceDiscoveryQualityReport:
    """Run the production ranker with external candidates and no builtin hints."""
    quality.validate_source_discovery_quality_corpus(corpus)
    hints = independent_discovery_hints(artifact)
    source_registry = registry or SourceRegistry()
    topics = sorted({case.topic for case in corpus.cases})
    results = {
        topic: discover_sources_for_topics(
            (topic,),
            source_registry,
            hints=hints,
            persist_registry=False,
            include_curated_seeds=False,
            include_builtin_hints=False,
            limit=corpus.recall_k,
        )
        for topic in topics
    }
    outcomes = tuple(
        quality._case_outcome(case, results[case.topic].items, corpus.recall_k)
        for case in corpus.cases
    )
    by_topic = quality._topic_metrics(corpus, results)
    by_family = quality._family_metrics(corpus, results)
    authority = quality._authority_metrics(corpus, outcomes, corpus.recall_k)
    metrics = quality._overall_metrics(corpus, results, outcomes)
    probe_outcomes = tuple(
        quality.ProbeOutcome(
            probe_id=probe.probe_id,
            stage=probe.stage,
            fixture_reference=probe.fixture_reference,
            outcome=quality.classify_deterministic_probe(probe),
        )
        for probe in corpus.probes
    )
    positive_outcomes = [row for row in outcomes if row.expected_discovered]
    negative_outcomes = [row for row in outcomes if not row.expected_discovered]
    outcome_counts = dict(sorted(Counter(row.outcome for row in positive_outcomes).items()))
    negative_outcome_counts = dict(
        sorted(Counter(row.outcome for row in negative_outcomes).items())
    )
    failures = Counter()
    for row in positive_outcomes:
        if row.outcome == "undiscovered":
            failures["undiscovered"] += 1
        elif row.outcome == "found_but_unsubscribable":
            failures["unsubscribable"] += 1
    failures.update(row.outcome for row in probe_outcomes if row.outcome != "covered")
    violations = list(quality._quality_violations(metrics, by_topic, corpus.floors))

    missing_topics = tuple(topic for topic in topics if not results[topic].items)
    evaluation_status = "scored" if not missing_topics else "not_evaluable"
    if missing_topics:
        violations.append(
            "evaluation_not_evaluable:independent_candidate_topic_coverage:"
            + ",".join(missing_topics)
        )

    return quality.SourceDiscoveryQualityReport(
        dataset_version=corpus.dataset_version,
        measurement_version=quality.MEASUREMENT_VERSION,
        production_version=corpus.production_version,
        source_sha=source_sha,
        split=corpus.split,
        execution_mode=corpus.execution_mode,
        blind_read=corpus.blind_read,
        gold_injected=corpus.gold_injected,
        human_gold=corpus.human_gold,
        label_source=corpus.label_source,
        hint_scope=corpus.hint_scope,
        evaluation_status=evaluation_status,
        live_qualification=corpus.live_qualification.model_dump(mode="json"),
        metrics=metrics,
        by_topic=by_topic,
        by_family=by_family,
        authority=authority,
        outcome_counts=outcome_counts,
        negative_outcome_counts=negative_outcome_counts,
        failure_class_counts=dict(sorted(failures.items())),
        probe_outcomes=probe_outcomes,
        cases=outcomes,
        floors=dict(sorted(corpus.floors.items())),
        violations=tuple(violations),
        passed=evaluation_status == "scored" and not violations,
    )
