"""Evaluation fixture for topic-driven source discovery precision/recall."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from app.services.source_discovery import SourceCandidate, SourceDiscoveryResult, discover_sources_for_topics
from app.services.source_registry import SourceRegistry, canonicalize_url

DATASET_VERSION = "source-discovery-v0.1"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceDiscoveryCase(_StrictModel):
    case_id: str = Field(min_length=1)
    topics: list[str] = Field(min_length=1)
    relevant_urls: list[str] = Field(min_length=1)
    irrelevant_substrings: list[str] = Field(default_factory=list)
    min_precision: float = 0.5
    min_recall: float = 0.4
    limit: int = 8


class SourceDiscoveryGold(_StrictModel):
    version: str
    cases: list[SourceDiscoveryCase]


@dataclass(frozen=True)
class CaseScore:
    case_id: str
    precision: float
    recall: float
    predicted: tuple[str, ...]
    relevant: tuple[str, ...]
    hits: tuple[str, ...]


@dataclass(frozen=True)
class SourceDiscoveryReport:
    version: str
    mean_precision: float
    mean_recall: float
    cases: tuple[CaseScore, ...]


def load_source_discovery_gold(path: Path) -> SourceDiscoveryGold:
    payload = json.loads(path.read_text())
    return SourceDiscoveryGold.model_validate(payload)


def canonical_relevant_urls(urls: Sequence[str]) -> set[str]:
    return {canonicalize_url(url) for url in urls}


def predicted_urls(items: Sequence[SourceCandidate]) -> tuple[str, ...]:
    return tuple(item.canonical_url for item in items)


def score_case(
    case: SourceDiscoveryCase,
    result: SourceDiscoveryResult,
) -> CaseScore:
    relevant = canonical_relevant_urls(case.relevant_urls)
    predicted = predicted_urls(result.items[: case.limit])
    hits = tuple(url for url in predicted if url in relevant)
    precision = len(hits) / len(predicted) if predicted else 0.0
    recall = len(set(hits)) / len(relevant) if relevant else 0.0
    return CaseScore(
        case_id=case.case_id,
        precision=precision,
        recall=recall,
        predicted=predicted,
        relevant=tuple(sorted(relevant)),
        hits=hits,
    )


def evaluate_source_discovery(
    gold: SourceDiscoveryGold,
    *,
    registry: SourceRegistry | None = None,
) -> SourceDiscoveryReport:
    source_registry = registry or SourceRegistry()
    scores: list[CaseScore] = []
    for case in gold.cases:
        result = discover_sources_for_topics(
            case.topics,
            source_registry,
            limit=case.limit,
        )
        scores.append(score_case(case, result))
    mean_precision = sum(item.precision for item in scores) / len(scores) if scores else 0.0
    mean_recall = sum(item.recall for item in scores) / len(scores) if scores else 0.0
    return SourceDiscoveryReport(
        version=gold.version,
        mean_precision=mean_precision,
        mean_recall=mean_recall,
        cases=tuple(scores),
    )
