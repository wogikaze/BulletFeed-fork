from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.evaluation.source_discovery_independent import (
    INDEPENDENT_CANDIDATE_VERSION,
    IndependentCandidate,
    IndependentCandidateArtifact,
    evaluate_source_discovery_quality_with_independent_candidates,
    load_independent_candidate_artifact,
    validate_independent_candidate_artifact,
)
from app.evaluation.source_discovery_quality import load_source_discovery_quality_corpus
from app.services.source_catalog import SourceKind
from app.services.source_discovery_seeds import DiscoveryProvenance
from app.services.source_registry import canonicalize_url
from app.services.user_interest import resolve_concept_id

_ROOT = Path(__file__).parent / "gold" / "source_discovery" / "v02"
_CORPUS = _ROOT / "corpus.json"


def _candidate(topic: str) -> IndependentCandidate:
    concept_id = resolve_concept_id(topic)
    return IndependentCandidate(
        url=canonicalize_url(f"https://example.com/{concept_id}"),
        family=SourceKind.GENERIC_WEB.value,
        concept_ids=[concept_id],
        provenance=DiscoveryProvenance.REPOSITORY_METADATA.value,
        title=f"Recorded candidate for {topic}",
        why="Recorded from an external repository-search fixture",
        display_name=f"{topic} external candidate",
        observed_via="github_repository_search",
        evidence_reference=f"https://api.github.com/search/repositories?q={concept_id}",
    )


def _artifact(topics: list[str]) -> IndependentCandidateArtifact:
    return IndependentCandidateArtifact(
        artifact_version=INDEPENDENT_CANDIDATE_VERSION,
        acquisition_mode="recorded_external",
        gold_read=False,
        collector_version="test-external-collector-v1",
        items=[_candidate(topic) for topic in topics],
    )


def test_independent_candidates_make_measurement_scored_without_making_it_pass() -> None:
    corpus = load_source_discovery_quality_corpus(_CORPUS)
    topics = sorted({case.topic for case in corpus.cases})
    report = evaluate_source_discovery_quality_with_independent_candidates(
        corpus,
        _artifact(topics),
    )

    assert report.evaluation_status == "scored"
    assert report.passed is False
    assert report.metrics["precision_at_20"] == 0.0
    assert not any(value.startswith("evaluation_not_evaluable:") for value in report.violations)


def test_partial_independent_candidates_remain_not_evaluable() -> None:
    corpus = load_source_discovery_quality_corpus(_CORPUS)
    topics = sorted({case.topic for case in corpus.cases})
    report = evaluate_source_discovery_quality_with_independent_candidates(
        corpus,
        _artifact(topics[:-1]),
    )

    assert report.evaluation_status == "not_evaluable"
    assert report.passed is False
    assert any(
        value.startswith("evaluation_not_evaluable:independent_candidate_topic_coverage:")
        for value in report.violations
    )


def test_curated_seed_provenance_is_rejected_as_independent_input() -> None:
    artifact = _artifact(["React"])
    broken = artifact.model_copy(
        update={
            "items": [
                artifact.items[0].model_copy(
                    update={"provenance": DiscoveryProvenance.CURATED_SEED.value}
                )
            ]
        }
    )
    with pytest.raises(ValueError, match="not independent"):
        validate_independent_candidate_artifact(broken)


def test_candidate_artifact_forbids_gold_label_fields(tmp_path: Path) -> None:
    item = _candidate("React").model_dump(mode="json")
    item["expected_discovered"] = True
    payload = {
        "artifact_version": INDEPENDENT_CANDIDATE_VERSION,
        "acquisition_mode": "recorded_external",
        "gold_read": False,
        "collector_version": "fixture-v1",
        "items": [item],
    }
    path = tmp_path / "candidates.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValidationError):
        load_independent_candidate_artifact(path)
