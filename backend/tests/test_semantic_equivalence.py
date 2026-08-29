from __future__ import annotations

import json
from pathlib import Path

from app.evaluation.delta_adversarial_gold import (
    DeltaAdversarialPrediction,
    evaluate_delta_adversarial,
    load_delta_adversarial_gold,
)
from app.evaluation.semantic_quality import binary_metrics
from app.services.claim_semantics import compare_claims
from app.services.semantic_delta import ClaimSnapshot, DeltaContext, judge_revision
from app.services.semantic_equivalence import (
    COMPARATOR_VERSION,
    DISABLED_MODEL_VERSION,
    ModelEvidence,
    SemanticEquivalenceComparator,
    compare_semantic_equivalence,
)

_V01 = Path(__file__).parent / "gold" / "delta_adversarial" / "v01"
_V02 = Path(__file__).parent / "gold" / "v02" / "blind" / "semantic_hard_cases.json"


class ScriptedEquivalenceModel:
    """Test-only stub. Demonstrates evidence-not-override; never used in production."""

    def __init__(
        self,
        *,
        label: str = "equivalent",
        confidence: str = "high",
        reason: str = "scripted paraphrase evidence",
        version: str = "stub-model-v1",
        prompt_version: str = "stub-prompt-v1",
        error: Exception | None = None,
    ) -> None:
        self.label = label
        self.confidence = confidence
        self.reason = reason
        self.version = version
        self.prompt_version = prompt_version
        self.error = error
        self.calls = 0

    def evaluate(self, *args, **kwargs) -> ModelEvidence:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return ModelEvidence(
            label=self.label,  # type: ignore[arg-type]
            reason=self.reason,
            confidence=self.confidence,  # type: ignore[arg-type]
            version=self.version,
            prompt_version=self.prompt_version,
        )


def test_default_path_works_without_a_model_and_is_versioned() -> None:
    decision = compare_semantic_equivalence(
        "active",
        "Limit increased to 1,000 requests per minute.",
        "active",
        "Limit was raised to one thousand requests/min.",
    )

    assert decision.label == "equivalent"
    assert decision.confidence in {"high", "medium"}
    assert decision.reason
    assert decision.version
    assert COMPARATOR_VERSION in decision.version
    assert "semantic-equivalence-v1" in decision.version
    assert DISABLED_MODEL_VERSION in decision.version
    assert decision.model_used is False
    assert decision.evidence is None
    assert decision.abstained is False


def test_hard_guards_cover_numeric_version_date_negation_and_stable_id() -> None:
    numeric = compare_semantic_equivalence(
        "limit 1000 requests/min",
        "API v2 rate limit is 1,000 requests per minute.",
        "limit 1200 requests/min",
        "API v2 rate limit is 1,200 requests per minute.",
    )
    version = compare_semantic_equivalence("fixed in v2.1.0", "", "fixed in v2.2.0", "")
    date = compare_semantic_equivalence(
        "retires",
        "Support retires July 30, 2026.",
        "retires",
        "Support retires August 30, 2026.",
    )
    negation = compare_semantic_equivalence(
        "supported",
        "Python 3.10 is supported",
        "not supported",
        "Python 3.10 is not supported",
    )
    stable_id = compare_semantic_equivalence(
        "affected",
        "CVE-2024-12345 is fixed in the latest release.",
        "affected",
        "CVE-2024-99999 is fixed in the latest release.",
    )

    assert numeric.label == "not_equivalent"
    assert "numeric" in numeric.hard_guards
    assert version.label == "not_equivalent"
    assert "version" in version.hard_guards
    assert date.label == "not_equivalent"
    assert "date" in date.hard_guards
    assert negation.label == "not_equivalent"
    assert "negation" in negation.hard_guards
    assert stable_id.label == "not_equivalent"
    assert "stable_id" in stable_id.hard_guards
    for decision in (numeric, version, date, negation, stable_id):
        assert decision.reason
        assert decision.confidence == "high"
        assert decision.version


def test_model_cannot_flip_hard_guard_to_equivalent() -> None:
    model = ScriptedEquivalenceModel(label="equivalent", confidence="high")
    decision = compare_semantic_equivalence(
        "limit 1000 requests/min",
        "",
        "limit 1200 requests/min",
        "",
        model=model,
        model_enabled=True,
    )

    assert model.calls == 1
    assert decision.model_used is True
    assert decision.evidence is not None
    assert decision.evidence.label == "equivalent"
    assert decision.label == "not_equivalent"
    assert decision.model_overridden is True
    assert "numeric" in decision.hard_guards
    assert "ignored" in decision.reason


def test_model_failure_falls_back_to_deterministic_path() -> None:
    model = ScriptedEquivalenceModel(error=RuntimeError("upstream timeout"))
    decision = compare_semantic_equivalence(
        "database latency issue",
        "",
        "database capacity issue",
        "",
        model=model,
        model_enabled=True,
    )

    assert model.calls == 1
    assert decision.model_used is False
    assert decision.label == "uncertain"
    assert decision.abstained is True
    assert "model failed" in decision.reason
    assert "RuntimeError" in decision.reason
    assert decision.confidence == "low"


def test_low_confidence_model_abstains_instead_of_merging() -> None:
    model = ScriptedEquivalenceModel(label="equivalent", confidence="low")
    decision = compare_semantic_equivalence(
        "database latency issue",
        "",
        "database capacity issue",
        "",
        model=model,
        model_enabled=True,
    )

    assert decision.label == "uncertain"
    assert decision.abstained is True
    assert decision.confidence == "low"
    assert "abstained" in decision.reason


def test_disabled_model_hook_is_never_invoked() -> None:
    model = ScriptedEquivalenceModel()
    decision = compare_semantic_equivalence(
        "database latency issue",
        "",
        "database capacity issue",
        "",
        model=model,
        model_enabled=False,
    )

    assert model.calls == 0
    assert decision.model_used is False
    assert decision.label == "uncertain"
    assert DISABLED_MODEL_VERSION in decision.version


def test_identical_canonical_pairs_are_cached() -> None:
    comparator = SemanticEquivalenceComparator()
    first = comparator.compare(
        "active",
        "Limit increased to 1,000 requests per minute.",
        "active",
        "Limit was raised to one thousand requests/min.",
    )
    second = comparator.compare(
        "active",
        "Limit increased to 1,000 requests per minute.",
        "active",
        "Limit was raised to one thousand requests/min.",
    )

    assert first.cache_hit is False
    assert second.cache_hit is True
    assert first.label == second.label == "equivalent"
    assert first.version == second.version


def test_typed_slots_recover_restated_limits_without_a_model() -> None:
    lexical = compare_claims(
        "active",
        "Limit increased to 1,000 requests per minute.",
        "active",
        "The per-minute request cap is now one thousand.",
    )
    decision = compare_semantic_equivalence(
        "active",
        "Limit increased to 1,000 requests per minute.",
        "active",
        "The per-minute request cap is now one thousand.",
    )

    assert lexical.label == "not_equivalent"
    assert decision.label == "equivalent"
    assert decision.model_used is False
    assert "typed slot restatement" in decision.reason


def test_unit_change_is_a_numeric_hard_guard() -> None:
    decision = compare_semantic_equivalence(
        "limit 1000 mb",
        "Upload limit increased to 1000 MB.",
        "limit 1000 gb",
        "Upload limit increased to 1000 GB.",
    )

    assert decision.label == "not_equivalent"
    assert "numeric" in decision.hard_guards
    assert decision.confidence == "high"


def test_high_confidence_model_may_support_paraphrase_when_unguarded() -> None:
    model = ScriptedEquivalenceModel(label="equivalent", confidence="high")
    decision = compare_semantic_equivalence(
        "affected",
        "The built-in CookieJar accepts unbounded response cookies.",
        "affected",
        "Guzzle CookieJar can store an unbounded number of Set-Cookie values from a single response.",
        model=model,
        model_enabled=True,
    )

    assert decision.hard_guards == ()
    assert decision.label == "equivalent"
    assert decision.model_used is True
    assert decision.model_overridden is False
    assert decision.confidence == "medium"
    assert "model evidence" in decision.reason


def test_english_v02_gold_does_not_regress_through_the_wrapper() -> None:
    dataset = json.loads(_V02.read_text(encoding="utf-8"))
    priors: dict[str, ClaimSnapshot] = {}
    expected: list[bool] = []
    predicted: list[bool] = []
    for bundle in dataset["bundles"]:
        for case in bundle["cases"]:
            candidate = ClaimSnapshot(case["value"], case["detail"], case["valid_at"])
            prior = priors.get(case["event_label"])
            if prior is not None:
                decision = compare_semantic_equivalence(
                    prior.value,
                    prior.detail,
                    candidate.value,
                    candidate.detail,
                )
                expected.append(case["expected_revision"] == "NON_NOVEL")
                predicted.append(decision.label == "equivalent")
                assert decision.reason
                assert decision.confidence
                assert decision.version
            revision = judge_revision(
                prior,
                candidate,
                context=DeltaContext(
                    explicit_correction=case.get("explicit_correction", False),
                    unresolved_source_conflict=case.get("unresolved_source_conflict", False),
                ),
            )
            if revision.revision_type != "UNRESOLVED_CONTRADICTION":
                priors[case["event_label"]] = candidate

    report = binary_metrics(tuple(expected), tuple(predicted))
    assert report.precision >= 0.95
    assert report.recall >= 0.95


def _predict_corpus(factory):
    corpus = load_delta_adversarial_gold(_V01)
    predicted: dict[str, DeltaAdversarialPrediction] = {}
    for case in corpus.cases:
        equivalence = factory(
            case.prior.value,
            case.prior.detail,
            case.candidate.value,
            case.candidate.detail,
        )
        decision = judge_revision(
            ClaimSnapshot(case.prior.value, case.prior.detail, case.prior.valid_at),
            ClaimSnapshot(case.candidate.value, case.candidate.detail, case.candidate.valid_at),
            context=DeltaContext(
                explicit_correction=case.explicit_correction,
                unresolved_source_conflict=case.unresolved_source_conflict,
            ),
        )
        predicted[case.case_id] = DeltaAdversarialPrediction(
            case_id=case.case_id,
            equivalence=equivalence.label,
            revision_class=decision.revision_type,
            same_event=decision.revision_type != "NEW_FACT",
        )
    return corpus, predicted


def test_adversarial_gold_reports_equivalence_precision_recall_false_merge_and_split() -> None:
    baseline_corpus, baseline_predicted = _predict_corpus(compare_claims)
    corpus, predicted = _predict_corpus(compare_semantic_equivalence)
    baseline = evaluate_delta_adversarial(baseline_corpus, baseline_predicted)
    report = evaluate_delta_adversarial(corpus, predicted)

    assert report.pair_count == len(corpus.cases)
    assert 0.0 <= report.equivalence.precision <= 1.0
    assert 0.0 <= report.equivalence.recall <= 1.0
    assert report.false_merge_count >= 0
    assert report.false_split_count >= 0
    assert report.equivalence.precision >= 0.95
    assert report.equivalence.recall >= baseline.equivalence.recall
    assert report.equivalence.recall > baseline.equivalence.recall
    assert report.false_merge_count <= baseline.false_merge_count

    for case in corpus.cases:
        decision = compare_semantic_equivalence(
            case.prior.value,
            case.prior.detail,
            case.candidate.value,
            case.candidate.detail,
        )
        assert decision.reason
        assert decision.confidence in {"high", "medium", "low"}
        assert decision.version
        if decision.label == "uncertain":
            assert decision.abstained is True
