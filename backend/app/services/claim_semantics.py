from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

EquivalenceLabel = Literal["equivalent", "not_equivalent", "uncertain"]
Confidence = Literal["high", "medium", "low"]

_NUMBER_WORDS = {
    "zero": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
    "eleven": "11",
    "twelve": "12",
    "thirteen": "13",
    "fourteen": "14",
    "fifteen": "15",
    "sixteen": "16",
    "seventeen": "17",
    "eighteen": "18",
    "nineteen": "19",
    "twenty": "20",
    "thirty": "30",
    "forty": "40",
    "fifty": "50",
    "sixty": "60",
    "seventy": "70",
    "eighty": "80",
    "ninety": "90",
    "one thousand": "1000",
}

_PHRASE_ALIASES = {
    "requests per minute": "requests/min",
    "request per minute": "requests/min",
    "per cent": "percent",
    "%": " percent ",
    "was raised to": "increased to",
    "has been raised to": "increased to",
    "was increased to": "increased to",
    "is no longer supported": "is not supported",
    "unsupported": "not supported",
    "unavailable": "not available",
}

_STOPWORDS = {
    "a",
    "an",
    "the",
    "is",
    "are",
    "was",
    "were",
    "has",
    "have",
    "been",
    "for",
}

_NEGATION_TOKENS = {"not", "no", "never", "without", "disabled", "removed"}
_VERSION_RE = re.compile(r"\bv?\d+(?:\.\d+){1,3}(?:[-+][a-z0-9.-]+)?\b", re.IGNORECASE)
_NUMBER_RE = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?![\w.])")
_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[._/-][a-z0-9]+)*|>=|<=|!=|==|>|<", re.IGNORECASE)
_DATE_PATTERNS = ("%B %d, %Y", "%b %d, %Y", "%Y/%m/%d")


@dataclass(frozen=True)
class SemanticEquivalencePolicy:
    equivalent_overlap: float = 0.90
    different_overlap: float = 0.45
    version: str = "semantic-equivalence-v1"

    @property
    def replay_version(self) -> str:
        return (
            f"{self.version}[equivalent_overlap={self.equivalent_overlap:.2f},"
            f"different_overlap={self.different_overlap:.2f}]"
        )


DEFAULT_EQUIVALENCE_POLICY = SemanticEquivalencePolicy()


@dataclass(frozen=True)
class CanonicalText:
    text: str
    tokens: tuple[str, ...]
    numbers: tuple[str, ...]
    versions: tuple[str, ...]
    negated: bool


@dataclass(frozen=True)
class CanonicalClaim:
    value: CanonicalText
    detail: CanonicalText


@dataclass(frozen=True)
class EquivalenceDecision:
    label: EquivalenceLabel
    reason: str
    confidence: Confidence
    version: str


def canonicalize_claim(
    value: str,
    detail: str,
    *,
    entity_aliases: Mapping[str, str] | None = None,
) -> CanonicalClaim:
    return CanonicalClaim(
        value=canonicalize_text(value, entity_aliases=entity_aliases),
        detail=canonicalize_text(detail, entity_aliases=entity_aliases),
    )


def canonicalize_text(
    value: str,
    *,
    entity_aliases: Mapping[str, str] | None = None,
) -> CanonicalText:
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    normalized = _normalize_dates(normalized)
    normalized = re.sub(r"(?<=\d),(?=\d)", "", normalized)

    aliases = dict(_PHRASE_ALIASES)
    if entity_aliases:
        aliases.update(
            {key.casefold(): replacement.casefold() for key, replacement in entity_aliases.items()}
        )
    for source, replacement in sorted(aliases.items(), key=lambda item: len(item[0]), reverse=True):
        normalized = re.sub(rf"(?<!\w){re.escape(source)}(?!\w)", replacement, normalized)

    for words, number in sorted(_NUMBER_WORDS.items(), key=lambda item: len(item[0]), reverse=True):
        normalized = re.sub(rf"\b{re.escape(words)}\b", number, normalized)

    versions = tuple(sorted(set(match.casefold().lstrip("v") for match in _VERSION_RE.findall(normalized))))
    numbers = tuple(sorted(set(_NUMBER_RE.findall(normalized))))
    raw_tokens = [token.casefold() for token in _TOKEN_RE.findall(normalized)]
    tokens = tuple(token for token in raw_tokens if token not in _STOPWORDS)
    text = " ".join(tokens)
    negated = any(token in _NEGATION_TOKENS for token in tokens)
    return CanonicalText(
        text=text,
        tokens=tokens,
        numbers=numbers,
        versions=versions,
        negated=negated,
    )


def compare_claim_texts(
    prior: CanonicalText,
    candidate: CanonicalText,
    *,
    policy: SemanticEquivalencePolicy = DEFAULT_EQUIVALENCE_POLICY,
) -> EquivalenceDecision:
    version = policy.replay_version
    if prior.text == candidate.text:
        return EquivalenceDecision("equivalent", "canonical text is identical", "high", version)
    if prior.versions != candidate.versions and (prior.versions or candidate.versions):
        return EquivalenceDecision("not_equivalent", "version identifiers changed", "high", version)
    if prior.numbers != candidate.numbers and (prior.numbers or candidate.numbers):
        return EquivalenceDecision("not_equivalent", "numeric facts changed", "high", version)
    if prior.negated != candidate.negated:
        return EquivalenceDecision("not_equivalent", "polarity or negation changed", "high", version)

    prior_tokens = set(prior.tokens)
    candidate_tokens = set(candidate.tokens)
    if prior_tokens and prior_tokens == candidate_tokens:
        return EquivalenceDecision(
            "equivalent", "same canonical tokens in different order", "high", version
        )
    if prior_tokens and candidate_tokens and prior_tokens < candidate_tokens:
        return EquivalenceDecision(
            "not_equivalent", "candidate adds factual detail", "medium", version
        )
    if prior_tokens and candidate_tokens and candidate_tokens < prior_tokens:
        return EquivalenceDecision(
            "not_equivalent", "candidate omits prior factual detail", "medium", version
        )

    union = prior_tokens | candidate_tokens
    overlap = len(prior_tokens & candidate_tokens) / len(union) if union else 1.0
    if overlap >= policy.equivalent_overlap:
        return EquivalenceDecision(
            "equivalent", "high token overlap after canonicalization", "medium", version
        )
    if overlap <= policy.different_overlap:
        return EquivalenceDecision(
            "not_equivalent", "canonical facts materially differ", "medium", version
        )
    return EquivalenceDecision(
        "uncertain", "deterministic semantic evidence is inconclusive", "low", version
    )


def compare_claims(
    prior_value: str,
    prior_detail: str,
    candidate_value: str,
    candidate_detail: str,
    *,
    entity_aliases: Mapping[str, str] | None = None,
    policy: SemanticEquivalencePolicy = DEFAULT_EQUIVALENCE_POLICY,
) -> EquivalenceDecision:
    prior = canonicalize_claim(prior_value, prior_detail, entity_aliases=entity_aliases)
    candidate = canonicalize_claim(candidate_value, candidate_detail, entity_aliases=entity_aliases)

    value_decision = compare_claim_texts(prior.value, candidate.value, policy=policy)
    if value_decision.label != "equivalent":
        return EquivalenceDecision(
            value_decision.label,
            f"value: {value_decision.reason}",
            value_decision.confidence,
            value_decision.version,
        )
    detail_decision = compare_claim_texts(prior.detail, candidate.detail, policy=policy)
    return EquivalenceDecision(
        detail_decision.label,
        f"detail: {detail_decision.reason}",
        detail_decision.confidence,
        detail_decision.version,
    )


def _normalize_dates(text: str) -> str:
    output = text
    month_pattern = re.compile(
        r"\b(?:january|february|march|april|may|june|july|august|september|october|november|december|"
        r"jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\s+\d{1,2},\s+\d{4}\b",
        re.IGNORECASE,
    )
    for match in list(month_pattern.finditer(output)):
        raw = match.group(0)
        parsed = None
        for pattern in _DATE_PATTERNS[:2]:
            try:
                parsed = datetime.strptime(raw.title(), pattern)
                break
            except ValueError:
                continue
        if parsed is not None:
            output = output.replace(raw, parsed.strftime("%Y-%m-%d"))
    output = re.sub(
        r"\b(\d{4})/(\d{1,2})/(\d{1,2})\b",
        lambda match: f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}",
        output,
    )
    return output
