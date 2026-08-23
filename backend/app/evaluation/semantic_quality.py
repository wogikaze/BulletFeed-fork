from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Confidence = Literal["high", "medium", "low"]


@dataclass(frozen=True)
class BinaryMetricReport:
    precision: float
    recall: float


@dataclass(frozen=True)
class RevisionMetricReport:
    macro_f1: float
    accuracy: float


@dataclass(frozen=True)
class ConfidenceBucket:
    confidence: Confidence
    samples: int
    accuracy: float
    abstention_rate: float


def binary_metrics(expected: tuple[bool, ...], predicted: tuple[bool, ...]) -> BinaryMetricReport:
    if len(expected) != len(predicted):
        raise ValueError("expected and predicted lengths differ")
    true_positive = sum(want and got for want, got in zip(expected, predicted, strict=True))
    predicted_positive = sum(predicted)
    actual_positive = sum(expected)
    return BinaryMetricReport(
        precision=true_positive / predicted_positive if predicted_positive else 1.0,
        recall=true_positive / actual_positive if actual_positive else 1.0,
    )


def revision_metrics(
    expected: tuple[str, ...],
    predicted: tuple[str, ...],
) -> RevisionMetricReport:
    if len(expected) != len(predicted):
        raise ValueError("expected and predicted lengths differ")
    if not expected:
        return RevisionMetricReport(0.0, 0.0)
    labels = sorted(set(expected) | set(predicted))
    f1_scores: list[float] = []
    for label in labels:
        true_positive = sum(
            want == label and got == label
            for want, got in zip(expected, predicted, strict=True)
        )
        false_positive = sum(
            want != label and got == label
            for want, got in zip(expected, predicted, strict=True)
        )
        false_negative = sum(
            want == label and got != label
            for want, got in zip(expected, predicted, strict=True)
        )
        positive_denominator = true_positive + false_positive
        actual_denominator = true_positive + false_negative
        precision = true_positive / positive_denominator if positive_denominator else 0.0
        recall = true_positive / actual_denominator if actual_denominator else 0.0
        f1_scores.append(2 * precision * recall / (precision + recall) if precision + recall else 0.0)
    accuracy = sum(
        want == got for want, got in zip(expected, predicted, strict=True)
    ) / len(expected)
    return RevisionMetricReport(sum(f1_scores) / len(f1_scores), accuracy)


def confidence_buckets(
    samples: tuple[tuple[Confidence, bool, bool], ...],
) -> tuple[ConfidenceBucket, ...]:
    result: list[ConfidenceBucket] = []
    for confidence in ("high", "medium", "low"):
        selected = tuple(sample for sample in samples if sample[0] == confidence)
        if not selected:
            continue
        result.append(
            ConfidenceBucket(
                confidence=confidence,
                samples=len(selected),
                accuracy=sum(correct for _, correct, _ in selected) / len(selected),
                abstention_rate=sum(abstained for _, _, abstained in selected) / len(selected),
            )
        )
    return tuple(result)
