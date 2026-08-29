from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from statistics import fmean

from app.evaluation.delta_adversarial_gold import (
    DeltaAdversarialCase,
    DeltaAdversarialCorpus,
    DeltaAdversarialPrediction,
    DeltaAdversarialReport,
    evaluate_delta_adversarial,
    token_jaccard,
)
from app.services.event_coreference import (
    DEFAULT_COREFERENCE_POLICY,
    CoreferenceDecision,
    CoreferenceInput,
    CoreferencePolicy,
    EventCandidate,
    compare_event_mentions,
)

LEXICAL_COREFERENCE_THRESHOLD = 0.75


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


@dataclass(frozen=True)
class CoreferenceIdentityReport:
    """False merge and false split are counted separately; they are not one error rate."""

    pair_count: int
    false_merge_count: int
    false_split_count: int
    same_event_recall: float
    same_event_precision: float
    uncertain_count: int


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


def compare_delta_adversarial_case(
    case: DeltaAdversarialCase,
    *,
    policy: CoreferencePolicy = DEFAULT_COREFERENCE_POLICY,
) -> CoreferenceDecision:
    """Score a #66 pair as cross-source mentions. Gold labels are not rewritten."""
    incoming = CoreferenceInput(
        source_type="rss_atom",
        source_key=f"{case.publisher}-candidate",
        source_event_id=f"{case.case_id}:candidate",
        title=case.candidate.detail,
        subject=f"{case.candidate.value} {case.candidate.detail}",
        valid_at=case.candidate.valid_at,
    )
    existing = EventCandidate(
        event_id=case.prior_event_id,
        source_type="json_feed",
        source_key=f"{case.publisher}-prior",
        source_event_id=f"{case.case_id}:prior",
        title=case.prior.detail,
        created_at=case.prior.valid_at,
        latest_value=case.prior.value,
        latest_detail=case.prior.detail,
        latest_valid_at=case.prior.valid_at,
        score=0.0,
    )
    return compare_event_mentions(incoming, existing, policy=policy)


def lexical_delta_coreference_decision(case: DeltaAdversarialCase) -> CoreferenceDecision:
    overlap = token_jaccard(case.prior.text, case.candidate.text)
    same = overlap >= LEXICAL_COREFERENCE_THRESHOLD
    return CoreferenceDecision(
        "same_event" if same else "different_event",
        f"lexical token overlap {overlap:.2f}",
        "medium",
        candidate_event_id=case.prior_event_id if same else None,
        score=overlap,
        version="lexical-coreference-baseline-v1",
    )


def coreference_as_delta_prediction(
    case: DeltaAdversarialCase,
    decision: CoreferenceDecision,
) -> DeltaAdversarialPrediction:
    same = decision.label == "same_event"
    return DeltaAdversarialPrediction(
        case_id=case.case_id,
        equivalence="equivalent" if same else "not_equivalent",
        revision_class="NON_NOVEL" if same else "NEW_FACT",
        same_event=same,
    )


def evaluate_coreference_identity(
    corpus: DeltaAdversarialCorpus,
    decisions: Mapping[str, CoreferenceDecision],
    *,
    split: str | None = None,
) -> tuple[CoreferenceIdentityReport, DeltaAdversarialReport]:
    scoped = corpus.for_split(split) if split is not None else corpus
    predicted = {
        case.case_id: coreference_as_delta_prediction(case, decisions[case.case_id])
        for case in scoped.cases
    }
    delta = evaluate_delta_adversarial(scoped, predicted, split=split)
    expected_same = tuple(case.same_gold_event for case in scoped.cases)
    predicted_same = tuple(predicted[case.case_id].same_event for case in scoped.cases)
    true_positive = sum(want and got for want, got in zip(expected_same, predicted_same, strict=True))
    predicted_positive = sum(predicted_same)
    actual_positive = sum(expected_same)
    uncertain = sum(1 for case in scoped.cases if decisions[case.case_id].label == "uncertain")
    identity = CoreferenceIdentityReport(
        pair_count=len(scoped.cases),
        false_merge_count=delta.false_merge_count,
        false_split_count=delta.false_split_count,
        same_event_recall=true_positive / actual_positive if actual_positive else 1.0,
        same_event_precision=true_positive / predicted_positive if predicted_positive else 1.0,
        uncertain_count=uncertain,
    )
    return identity, delta
