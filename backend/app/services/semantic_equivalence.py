"""Model-assisted semantic equivalence with a deterministic abstention fallback.

LLM / embedding / NLI output is decision evidence only. It never writes ledger
truth and cannot flip a hard guard (numeric, version, date, negation, stable ID)
to equivalent. With no model configured the claim_semantics + claim_slots +
multilingual path still works and prefers a false split over a false merge.
"""

from __future__ import annotations

import re
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Literal, Protocol

from app.services.claim_semantics import (
    DEFAULT_EQUIVALENCE_POLICY,
    CanonicalClaim,
    EquivalenceDecision,
    EquivalenceLabel,
    SemanticEquivalencePolicy,
    canonicalize_claim,
    canonicalize_text,
    compare_claims,
)
from app.services.claim_slots import (
    TypedSlotDelta,
    compare_typed_slots,
    extract_claim_slots,
    normalize_date,
)
from app.services.multilingual_normalize import extract_identifiers, prepare_for_english_canonicalize

Confidence = Literal["high", "medium", "low"]
COMPARATOR_VERSION = "semantic-equivalence-v2"
DISABLED_MODEL_VERSION = "model-off-v1"
_CACHE_SIZE = 256
_ISO_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_VALUE_SLOTS = frozenset(
    {
        "version",
        "price",
        "limit",
        "quota",
        "effective_date",
        "deprecation_date",
        "affected_version_range",
    }
)
_STRUCTURAL_MARKERS = (
    "candidate adds factual detail",
    "candidate omits prior factual detail",
)
_VALUE_GUARD_MARKERS = ("numeric facts changed", "version identifiers changed")
DEFAULT_ENTITY_ALIASES = {
    "node.js": "nodejs",
    "node": "nodejs",
    "twitter api": "x api",
    "twitter": "x",
    "azure active directory": "microsoft entra id",
    "azure ad": "microsoft entra id",
}


@dataclass(frozen=True)
class ModelEvidence:
    """Optional model/NLI/embedding output. Evidence, not settled truth."""

    label: EquivalenceLabel
    reason: str
    confidence: Confidence
    version: str
    prompt_version: str = "none"


class EquivalenceModel(Protocol):
    def evaluate(
        self,
        prior_value: str,
        prior_detail: str,
        candidate_value: str,
        candidate_detail: str,
        *,
        canonical_prior: str,
        canonical_candidate: str,
    ) -> ModelEvidence | None:
        """Return typed evidence or None to abstain. Default implementations must not use the network."""


@dataclass(frozen=True)
class SemanticEquivalenceDecision:
    label: EquivalenceLabel
    reason: str
    confidence: Confidence
    version: str
    deterministic_label: EquivalenceLabel
    model_used: bool = False
    model_overridden: bool = False
    abstained: bool = False
    cache_hit: bool = False
    hard_guards: tuple[str, ...] = ()
    evidence: ModelEvidence | None = None

    def as_equivalence_decision(self) -> EquivalenceDecision:
        return EquivalenceDecision(self.label, self.reason, self.confidence, self.version)


class SemanticEquivalenceComparator:
    """Wraps compare_claims with hard guards, typed slots, and an optional model hook."""

    def __init__(
        self,
        *,
        model: EquivalenceModel | None = None,
        model_enabled: bool = False,
        policy: SemanticEquivalencePolicy = DEFAULT_EQUIVALENCE_POLICY,
        entity_aliases: Mapping[str, str] | None = None,
        cache_size: int = _CACHE_SIZE,
    ) -> None:
        self.model = model
        self.model_enabled = model_enabled and model is not None
        self.policy = policy
        self.entity_aliases = dict(DEFAULT_ENTITY_ALIASES)
        if entity_aliases:
            self.entity_aliases.update(entity_aliases)
        self._cache: OrderedDict[tuple[str, ...], SemanticEquivalenceDecision] = OrderedDict()
        self._cache_size = cache_size

    @property
    def model_version(self) -> str:
        if not self.model_enabled or self.model is None:
            return DISABLED_MODEL_VERSION
        version = getattr(self.model, "version", None)
        prompt = getattr(self.model, "prompt_version", "none")
        if isinstance(version, str) and version:
            return f"{version}/prompt={prompt}"
        return f"configured-model/prompt={prompt}"

    @property
    def replay_version(self) -> str:
        return f"{COMPARATOR_VERSION}+{self.policy.replay_version}+model={self.model_version}"

    def clear_cache(self) -> None:
        self._cache.clear()

    def compare(
        self,
        prior_value: str,
        prior_detail: str,
        candidate_value: str,
        candidate_detail: str,
        *,
        entity_aliases: Mapping[str, str] | None = None,
    ) -> SemanticEquivalenceDecision:
        aliases = dict(self.entity_aliases)
        if entity_aliases:
            aliases.update(entity_aliases)
        prior = canonicalize_claim(prior_value, prior_detail, entity_aliases=aliases)
        candidate = canonicalize_claim(candidate_value, candidate_detail, entity_aliases=aliases)
        cache_key = (
            prior.value.text,
            prior.detail.text,
            candidate.value.text,
            candidate.detail.text,
            self.replay_version,
        )
        cached = self._cache.get(cache_key)
        if cached is not None:
            self._cache.move_to_end(cache_key)
            return replace(cached, cache_hit=True)

        decision = self._decide(
            prior_value,
            prior_detail,
            candidate_value,
            candidate_detail,
            prior=prior,
            candidate=candidate,
            aliases=aliases,
        )
        self._store(cache_key, decision)
        return decision

    def _store(
        self,
        key: tuple[str, ...],
        decision: SemanticEquivalenceDecision,
    ) -> None:
        self._cache[key] = decision
        self._cache.move_to_end(key)
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)

    def _decide(
        self,
        prior_value: str,
        prior_detail: str,
        candidate_value: str,
        candidate_detail: str,
        *,
        prior: CanonicalClaim,
        candidate: CanonicalClaim,
        aliases: Mapping[str, str],
    ) -> SemanticEquivalenceDecision:
        deterministic = compare_claims(
            prior_value,
            prior_detail,
            candidate_value,
            candidate_detail,
            entity_aliases=aliases,
            policy=self.policy,
        )
        slot_delta = _slot_delta(prior_value, prior_detail, candidate_value, candidate_detail)
        guards = _hard_guards(prior, candidate, prior_value, prior_detail, candidate_value, candidate_detail)
        guards = _apply_slot_guards(guards, slot_delta)

        label, confidence, reason = _deterministic_verdict(deterministic, slot_delta, guards)
        blocked = bool(guards) or _is_structural_split(deterministic.reason)
        evidence: ModelEvidence | None = None
        model_used = False
        model_overridden = False

        if self.model_enabled and self.model is not None:
            try:
                evidence = self.model.evaluate(
                    prior_value,
                    prior_detail,
                    candidate_value,
                    candidate_detail,
                    canonical_prior=_canonical_pair(prior),
                    canonical_candidate=_canonical_pair(candidate),
                )
            except Exception as exc:  # noqa: BLE001 — model failure must not corrupt ledger state
                reason = (
                    f"{reason}; model failed ({type(exc).__name__}), using deterministic fallback"
                )
            else:
                if evidence is not None:
                    model_used = True
                    label, confidence, reason, model_overridden = _apply_model_evidence(
                        label,
                        confidence,
                        reason,
                        evidence=evidence,
                        blocked=blocked,
                        deterministic=deterministic,
                    )

        return SemanticEquivalenceDecision(
            label=label,
            reason=reason,
            confidence=confidence,
            version=self.replay_version,
            deterministic_label=deterministic.label,
            model_used=model_used,
            model_overridden=model_overridden,
            abstained=label == "uncertain",
            hard_guards=guards,
            evidence=evidence,
        )


DEFAULT_COMPARATOR = SemanticEquivalenceComparator()


def compare_semantic_equivalence(
    prior_value: str,
    prior_detail: str,
    candidate_value: str,
    candidate_detail: str,
    *,
    entity_aliases: Mapping[str, str] | None = None,
    policy: SemanticEquivalencePolicy = DEFAULT_EQUIVALENCE_POLICY,
    model: EquivalenceModel | None = None,
    model_enabled: bool = False,
    comparator: SemanticEquivalenceComparator | None = None,
) -> SemanticEquivalenceDecision:
    """Compare two claims. Model hook is off by default and never required."""
    if comparator is not None:
        return comparator.compare(
            prior_value,
            prior_detail,
            candidate_value,
            candidate_detail,
            entity_aliases=entity_aliases,
        )
    if model is not None or policy is not DEFAULT_EQUIVALENCE_POLICY:
        return SemanticEquivalenceComparator(
            model=model,
            model_enabled=model_enabled,
            policy=policy,
            entity_aliases=entity_aliases,
        ).compare(prior_value, prior_detail, candidate_value, candidate_detail)
    return DEFAULT_COMPARATOR.compare(
        prior_value,
        prior_detail,
        candidate_value,
        candidate_detail,
        entity_aliases=entity_aliases,
    )


def _canonical_pair(claim: CanonicalClaim) -> str:
    return f"{claim.value.text} | {claim.detail.text}"


def _slot_delta(
    prior_value: str,
    prior_detail: str,
    candidate_value: str,
    candidate_detail: str,
) -> TypedSlotDelta | None:
    prior = extract_claim_slots(prior_detail, value_text=prior_value, detail_text=prior_detail)
    candidate = extract_claim_slots(
        candidate_detail,
        value_text=candidate_value,
        detail_text=candidate_detail,
    )
    return compare_typed_slots(prior, candidate)


def _hard_guards(
    prior: CanonicalClaim,
    candidate: CanonicalClaim,
    prior_value: str,
    prior_detail: str,
    candidate_value: str,
    candidate_detail: str,
) -> tuple[str, ...]:
    guards: list[str] = []
    if _feature_changed(prior.value.versions, candidate.value.versions) or _feature_changed(
        prior.detail.versions, candidate.detail.versions
    ):
        guards.append("version")
    if _feature_changed(prior.value.numbers, candidate.value.numbers) or _feature_changed(
        prior.detail.numbers, candidate.detail.numbers
    ):
        guards.append("numeric")
    if prior.value.negated != candidate.value.negated or prior.detail.negated != candidate.detail.negated:
        guards.append("negation")

    prior_dates = _extract_dates(prior_value, prior_detail)
    candidate_dates = _extract_dates(candidate_value, candidate_detail)
    if prior_dates and candidate_dates and prior_dates != candidate_dates:
        guards.append("date")

    prior_ids = _stable_ids(prior_value, prior_detail)
    candidate_ids = _stable_ids(candidate_value, candidate_detail)
    if prior_ids and candidate_ids and prior_ids != candidate_ids:
        guards.append("stable_id")
    return tuple(dict.fromkeys(guards))


def _apply_slot_guards(
    guards: tuple[str, ...],
    slot_delta: TypedSlotDelta | None,
) -> tuple[str, ...]:
    remaining = list(guards)
    if slot_delta is None or slot_delta.slot not in _VALUE_SLOTS:
        return tuple(remaining)
    mapped = _slot_guard_name(slot_delta.slot)
    if slot_delta.kind == "same_slot_value_change":
        remaining.append(mapped)
        return tuple(dict.fromkeys(remaining))
    if slot_delta.kind == "same_slot_equivalent":
        return tuple(item for item in remaining if item != mapped)
    return tuple(remaining)


def _slot_guard_name(slot: str) -> str:
    if slot in {"version", "affected_version_range"}:
        return "version"
    if slot in {"effective_date", "deprecation_date"}:
        return "date"
    return "numeric"


def _deterministic_verdict(
    deterministic: EquivalenceDecision,
    slot_delta: TypedSlotDelta | None,
    guards: tuple[str, ...],
) -> tuple[EquivalenceLabel, Confidence, str]:
    if guards:
        return (
            "not_equivalent",
            "high",
            f"hard guard ({', '.join(guards)}): {deterministic.reason}",
        )
    if (
        slot_delta is not None
        and slot_delta.kind == "same_slot_equivalent"
        and slot_delta.slot in _VALUE_SLOTS
        and (
            deterministic.label == "uncertain"
            or any(marker in deterministic.reason for marker in _VALUE_GUARD_MARKERS)
        )
    ):
        confidence: Confidence = "high" if slot_delta.confidence == "high" else "medium"
        return (
            "equivalent",
            confidence,
            f"typed slot restatement: {slot_delta.reason}; {deterministic.reason}",
        )
    return deterministic.label, deterministic.confidence, deterministic.reason


def _is_structural_split(reason: str) -> bool:
    return any(marker in reason for marker in _STRUCTURAL_MARKERS)


def _apply_model_evidence(
    label: EquivalenceLabel,
    confidence: Confidence,
    reason: str,
    *,
    evidence: ModelEvidence,
    blocked: bool,
    deterministic: EquivalenceDecision,
) -> tuple[EquivalenceLabel, Confidence, str, bool]:
    evidence_note = f"{evidence.version}/prompt={evidence.prompt_version}: {evidence.reason}"
    if evidence.confidence == "low":
        if blocked:
            return label, confidence, f"{reason}; low-confidence model ignored ({evidence_note})", False
        return (
            "uncertain",
            "low",
            f"model abstained (low confidence): {evidence_note}; deterministic={deterministic.label}",
            False,
        )
    if evidence.label == "equivalent":
        if blocked:
            return (
                label,
                confidence,
                f"{reason}; model evidence ignored ({evidence_note})",
                True,
            )
        if evidence.confidence == "high":
            return (
                "equivalent",
                "medium",
                f"model evidence: {evidence_note}; deterministic={deterministic.label}",
                False,
            )
        if label != "equivalent":
            return (
                "uncertain",
                "low",
                f"medium-confidence model evidence abstained: {evidence_note}",
                False,
            )
        return label, confidence, f"{reason}; model agrees ({evidence_note})", False
    if evidence.label == "not_equivalent":
        if _is_identical_restatement(deterministic.reason):
            return (
                label,
                confidence,
                f"{reason}; model not_equivalent ignored for identical canonical text",
                False,
            )
        if evidence.confidence == "high" and label == "uncertain":
            return (
                "not_equivalent",
                "medium",
                f"model evidence: {evidence_note}; deterministic={deterministic.label}",
                False,
            )
        return label, confidence, f"{reason}; model evidence recorded ({evidence_note})", False
    if label == "equivalent" and not _is_identical_restatement(deterministic.reason):
        return (
            "uncertain",
            "low",
            f"model uncertain against overlap-only equivalent; abstaining ({evidence_note})",
            False,
        )
    return label, confidence, f"{reason}; model uncertain ({evidence_note})", False


def _is_identical_restatement(reason: str) -> bool:
    return "canonical text is identical" in reason or "same canonical tokens" in reason


def _feature_changed(prior: tuple[str, ...], candidate: tuple[str, ...]) -> bool:
    return prior != candidate and bool(prior or candidate)


def _extract_dates(*texts: str) -> frozenset[str]:
    found: set[str] = set()
    for text in texts:
        prepared = prepare_for_english_canonicalize(text)
        found.update(_ISO_DATE_RE.findall(prepared))
        found.update(_ISO_DATE_RE.findall(canonicalize_text(text).text))
        dated = normalize_date(text)
        if dated:
            found.add(dated)
    return frozenset(found)


def _stable_ids(*texts: str) -> frozenset[str]:
    found: set[str] = set()
    for text in texts:
        for item in extract_identifiers(text):
            key = item.casefold()
            if key.startswith("cve-") or key.startswith("ghsa-"):
                found.add(key)
    return frozenset(found)
