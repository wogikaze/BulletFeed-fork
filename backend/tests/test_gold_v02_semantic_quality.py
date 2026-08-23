import json
from pathlib import Path

from app.evaluation.semantic_quality import binary_metrics, confidence_buckets, revision_metrics
from app.services.claim_semantics import compare_claims
from app.services.semantic_delta import ClaimSnapshot, DeltaContext, judge_revision

_GOLD = Path(__file__).parent / "gold" / "v02" / "blind" / "semantic_hard_cases.json"


def test_blind_semantic_quality_reports_equivalence_revision_and_confidence_metrics():
    dataset = json.loads(_GOLD.read_text(encoding="utf-8"))
    priors: dict[str, ClaimSnapshot] = {}
    equivalence_expected: list[bool] = []
    equivalence_predicted: list[bool] = []
    revision_expected: list[str] = []
    revision_predicted: list[str] = []
    calibration_samples: list[tuple[str, bool, bool]] = []

    for bundle in dataset["bundles"]:
        for case in bundle["cases"]:
            label = case["event_label"]
            candidate = ClaimSnapshot(
                value=case["value"],
                detail=case["detail"],
                valid_at=case["valid_at"],
            )
            prior = priors.get(label)
            decision = judge_revision(
                prior,
                candidate,
                context=DeltaContext(
                    explicit_correction=case.get("explicit_correction", False),
                    unresolved_source_conflict=case.get("unresolved_source_conflict", False),
                ),
            )
            expected_revision = case["expected_revision"]
            revision_expected.append(expected_revision)
            revision_predicted.append(decision.revision_type)
            calibration_samples.append(
                (
                    decision.confidence,
                    decision.revision_type == expected_revision,
                    decision.abstained,
                )
            )

            if prior is not None:
                equivalence = compare_claims(
                    prior.value,
                    prior.detail,
                    candidate.value,
                    candidate.detail,
                )
                equivalence_expected.append(expected_revision == "NON_NOVEL")
                equivalence_predicted.append(equivalence.label == "equivalent")
            if decision.revision_type != "UNRESOLVED_CONTRADICTION":
                priors[label] = candidate

    equivalence_report = binary_metrics(
        tuple(equivalence_expected), tuple(equivalence_predicted)
    )
    revision_report = revision_metrics(
        tuple(revision_expected), tuple(revision_predicted)
    )
    buckets = confidence_buckets(tuple(calibration_samples))

    assert equivalence_report.precision >= 0.95
    assert equivalence_report.recall >= 0.95
    assert revision_report.macro_f1 >= 0.90
    assert revision_report.accuracy >= 0.95
    assert buckets
    for bucket in buckets:
        if bucket.confidence in {"high", "medium"}:
            assert bucket.accuracy >= 0.90


def test_low_confidence_semantic_change_abstains_from_state_update():
    decision = judge_revision(
        ClaimSnapshot(
            value="service capacity enabled",
            detail="Capacity policy is active for standard users",
            valid_at="2026-08-01T00:00:00Z",
        ),
        ClaimSnapshot(
            value="service capacity policy",
            detail="Capacity policy changes for selected users",
            valid_at="2026-08-02T00:00:00Z",
        ),
    )

    assert decision.revision_type == "UNRESOLVED_CONTRADICTION"
    assert decision.confidence == "low"
    assert decision.abstained is True
    assert decision.version == "revision-judge-v1"
    assert "semantic-equivalence-v1" in decision.reason
    assert "equivalent_overlap=0.90" in decision.reason
