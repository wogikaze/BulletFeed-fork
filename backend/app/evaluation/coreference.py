from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean


@dataclass(frozen=True)
class CandidateRetrievalSample:
    expected_event_id: str
    candidate_event_ids: tuple[str, ...]


@dataclass(frozen=True)
class CandidateRetrievalReport:
    samples: int
    hits: int
    candidate_recall: float
    average_candidate_set_size: float
    max_candidate_set_size: int


def evaluate_candidate_retrieval(
    samples: tuple[CandidateRetrievalSample, ...],
) -> CandidateRetrievalReport:
    if not samples:
        return CandidateRetrievalReport(0, 0, 0.0, 0.0, 0)
    sizes = tuple(len(sample.candidate_event_ids) for sample in samples)
    hits = sum(
        sample.expected_event_id in sample.candidate_event_ids
        for sample in samples
    )
    return CandidateRetrievalReport(
        samples=len(samples),
        hits=hits,
        candidate_recall=hits / len(samples),
        average_candidate_set_size=fmean(sizes),
        max_candidate_set_size=max(sizes),
    )
