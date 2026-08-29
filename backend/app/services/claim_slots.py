"""Optional typed Claim slots extracted from unstructured Observation text.

Extraction is additive: raw Claim/Evidence text is preserved and never replaced.
Unknown or low-confidence slot/value pairs abstain rather than guess.
Structured source fields are authoritative over prose. Numeric, unit, and version
normalization is deterministic and never flips comparator direction.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

SlotName = Literal[
    "version",
    "price",
    "limit",
    "quota",
    "availability",
    "status",
    "effective_date",
    "supported_platform",
    "affected_version_range",
    "severity",
    "incident_status",
    "deprecation_date",
]
Confidence = Literal["high", "medium", "low"]
ValueOrigin = Literal["structured", "value", "prose"]
TypedDeltaKind = Literal["same_slot_value_change", "different_slot_added", "same_slot_equivalent"]
RevisionHint = Literal["STATE_UPDATE", "DETAIL"]

_CONFIDENCE_RANK = {"high": 3, "medium": 2, "low": 1}
_MIN_CONSUMABLE = "medium"

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
    "two thousand": "2000",
}

_UNIT_ALIASES = {
    "kb": "KB",
    "kilobyte": "KB",
    "kilobytes": "KB",
    "mb": "MB",
    "megabyte": "MB",
    "megabytes": "MB",
    "gb": "GB",
    "gigabyte": "GB",
    "gigabytes": "GB",
    "tb": "TB",
    "terabyte": "TB",
    "terabytes": "TB",
    "s": "s",
    "sec": "s",
    "secs": "s",
    "second": "s",
    "seconds": "s",
    "m": "min",
    "min": "min",
    "mins": "min",
    "minute": "min",
    "minutes": "min",
    "h": "hour",
    "hr": "hour",
    "hrs": "hour",
    "hour": "hour",
    "hours": "hour",
    "d": "day",
    "day": "day",
    "days": "day",
    "requests/min": "requests/min",
    "request/min": "requests/min",
    "req/min": "requests/min",
    "requests per minute": "requests/min",
    "request per minute": "requests/min",
    "requests/hour": "requests/hour",
    "request/hour": "requests/hour",
    "requests per hour": "requests/hour",
    "request per hour": "requests/hour",
    "requests/day": "requests/day",
    "request/day": "requests/day",
    "requests per day": "requests/day",
    "request per day": "requests/day",
    "requests/15min": "requests/15min",
    "requests per 15 minutes": "requests/15min",
    "request per 15 minutes": "requests/15min",
    "per-minute": "requests/min",
    "per minute": "requests/min",
    "per hour": "requests/hour",
    "per day": "requests/day",
    "/15m": "requests/15min",
    "/hour": "requests/hour",
    "/day": "requests/day",
    "/min": "requests/min",
}

_STRUCTURED_SLOT_KEYS: dict[str, SlotName] = {
    "version": "version",
    "tag_name": "version",
    "price": "price",
    "limit": "limit",
    "quota": "quota",
    "rate_limit": "limit",
    "availability": "availability",
    "status": "status",
    "incident_status": "incident_status",
    "severity": "severity",
    "effective_date": "effective_date",
    "deprecation_date": "deprecation_date",
    "removal_date": "deprecation_date",
    "eol_date": "deprecation_date",
    "supported_platform": "supported_platform",
    "platform": "supported_platform",
    "affected_version_range": "affected_version_range",
    "affected_versions": "affected_version_range",
}

_ENTITY_ALIASES = {
    "node": "nodejs",
    "node.js": "nodejs",
    "nodejs": "nodejs",
    "twitter api": "x api",
    "twitter": "x",
    "azure active directory": "microsoft entra id",
    "azure ad": "microsoft entra id",
}

_PRODUCTS = (
    "react native",
    "microsoft entra id",
    "azure active directory",
    "twitter api",
    "node.js",
    "log4j-core",
    "github actions",
    "python",
    "guzzle",
    "openssl",
    "nodejs",
    "widget",
    "react",
    "node",
    "twitter",
    "x api",
)

_INCIDENT_STATUS = frozenset(
    {
        "investigating",
        "identified",
        "monitoring",
        "resolved",
        "mitigated",
        "degraded",
        "operational",
        "major_outage",
        "partial_outage",
    }
)
_AVAILABILITY = {
    "available": "available",
    "unavailable": "unavailable",
    "not available": "unavailable",
    "generally available": "available",
    "ga": "available",
    "released": "released",
    "prerelease": "prerelease",
    "draft": "draft",
    "withdrawn": "withdrawn",
    "supported": "supported",
    "not supported": "unsupported",
    "unsupported": "unsupported",
    "eol": "eol",
    "deprecated": "deprecated",
}
_SEVERITY = frozenset({"critical", "high", "medium", "moderate", "low"})
_COMPARATORS = (">=", "<=", "!=", "==", ">", "<")
_COMPARATOR_WORDS = (
    (re.compile(r"\bat\s+least\b", re.IGNORECASE), ">="),
    (re.compile(r"\bminimum\b", re.IGNORECASE), ">="),
    (re.compile(r"\bor\s+later\b", re.IGNORECASE), ">="),
    (re.compile(r"\bor\s+higher\b", re.IGNORECASE), ">="),
    (re.compile(r"\band\s+above\b", re.IGNORECASE), ">="),
    (re.compile(r"\bat\s+most\b", re.IGNORECASE), "<="),
    (re.compile(r"\bmaximum\b", re.IGNORECASE), "<="),
    (re.compile(r"\bor\s+earlier\b", re.IGNORECASE), "<="),
    (re.compile(r"\bor\s+lower\b", re.IGNORECASE), "<="),
    (re.compile(r"\band\s+below\b", re.IGNORECASE), "<="),
    (re.compile(r"\bup\s+to\b", re.IGNORECASE), "<="),
    (re.compile(r"\bgreater\s+than\b", re.IGNORECASE), ">"),
    (re.compile(r"\bless\s+than\b", re.IGNORECASE), "<"),
)
_COMPARATOR_NORMALIZE = {"≥": ">=", "≤": "<=", "≠": "!=", "=": "=="}

_DATE_MONTH = re.compile(
    r"\b(?P<month>january|february|march|april|may|june|july|august|september|october|"
    r"november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)"
    r"\s+(?P<day>\d{1,2}),\s+(?P<year>\d{4})\b",
    re.IGNORECASE,
)
_DATE_YMD = re.compile(r"\b(?P<year>\d{4})[-/](?P<month>\d{1,2})[-/](?P<day>\d{1,2})\b")
_DATE_PATTERNS = ("%B %d, %Y", "%b %d, %Y")
_VERSION_RE = re.compile(r"\bv?(?P<version>\d+(?:\.\d+){1,3}(?:[-+][a-z0-9.-]+)?)\b", re.IGNORECASE)
_NUMBER_RE = re.compile(r"(?<![\w.])(?P<number>-?\d+(?:\.\d+)?)(?![\w]|\.\d)")
_PRICE_RE = re.compile(
    r"(?P<currency>\$|usd|eur|jpy|¥|€)\s*(?P<amount>\d+(?:,\d{3})*(?:\.\d+)?)"
    r"(?:\s*/\s*(?P<period>[a-z]+))?",
    re.IGNORECASE,
)
_LIMIT_UNIT_RE = re.compile(
    r"(?P<number>-?\d+(?:\.\d+)?|one thousand|two thousand)"
    r"\s*(?P<unit>"
    r"kb|mb|gb|tb|kilobytes?|megabytes?|gigabytes?|terabytes?|"
    r"seconds?|minutes?|hours?|days?|secs?|mins?|hrs?|"
    r"requests?\s+per\s+(?:minute|hour|day|15\s+minutes)|"
    r"req(?:uests)?/(?:min|hour|day)|"
    r"/15m|/hour|/day|/min"
    r")",
    re.IGNORECASE,
)
_LIMIT_COMPACT_RE = re.compile(
    r"\b(?:limit|quota|cap|timeout)\s+"
    r"(?P<number>-?\d+(?:\.\d+)?)"
    r"\s*(?P<unit>kb|mb|gb|tb|/hour|/day|/min|/15m|s|m|h|d)?\b",
    re.IGNORECASE,
)
_RANGE_RE = re.compile(
    r"(?P<comparator>>=|<=|!=|==|>|<|≥|≤)\s*"
    r"v?(?P<version>\d+(?:\.\d+){0,3})",
    re.IGNORECASE,
)
_PLATFORM_RE = re.compile(
    r"\b(?:supported|available)\s+(?:on|for)\s+(?P<platform>ios|android|windows|macos|linux|web)\b",
    re.IGNORECASE,
)
_DEPRECATION_HINT = re.compile(
    r"\b(?:eol|end(?:s|ed)?|retir(?:e|es|ed)|deprecat(?:e|es|ed|ion)|remov(?:e|es|ed|al))\b",
    re.IGNORECASE,
)
_EFFECTIVE_HINT = re.compile(r"\b(?:effective|as of|starting|begins?)\b", re.IGNORECASE)
_LIMIT_HINT = re.compile(r"\b(?:limit|quota|cap|timeout|rate\s+limit)\b", re.IGNORECASE)
_QUOTA_HINT = re.compile(r"\bquota\b", re.IGNORECASE)
_TIMEOUT_HINT = re.compile(r"\btimeout\b", re.IGNORECASE)


@dataclass(frozen=True)
class TypedClaimSlot:
    entity: str | None
    slot: SlotName
    value: str
    unit: str | None
    comparator: str | None
    qualifiers: tuple[str, ...]
    valid_at: str | None
    confidence: Confidence
    origin: ValueOrigin
    raw_span: str

    @property
    def identity(self) -> tuple[str, str | None, str | None]:
        return (self.value, self.unit, self.comparator)


@dataclass(frozen=True)
class ClaimSlotExtraction:
    evidence_text: str
    slots: tuple[TypedClaimSlot, ...]
    abstained: bool

    def slots_named(self, slot: SlotName) -> tuple[TypedClaimSlot, ...]:
        return tuple(item for item in self.slots if item.slot == slot)


@dataclass(frozen=True)
class TypedSlotDelta:
    kind: TypedDeltaKind
    slot: SlotName
    prior_value: str | None
    candidate_value: str | None
    confidence: Literal["high", "medium"]
    reason: str


def extract_claim_slots(
    evidence_text: str,
    *,
    structured: Mapping[str, Any] | None = None,
    entity: str | None = None,
    valid_at: str | None = None,
    value_text: str = "",
    detail_text: str = "",
) -> ClaimSlotExtraction:
    """Extract typed slots without mutating or replacing raw Evidence."""
    evidence = evidence_text
    structured_slots = _extract_structured(structured, entity=entity, valid_at=valid_at)
    value_slots = _extract_value_field(value_text, entity=entity, valid_at=valid_at)
    prose = _unique_text(value_text, detail_text, evidence_text)
    prose_slots = _extract_prose(prose, entity=entity, valid_at=valid_at)
    merged = _merge_authoritative(structured_slots, value_slots, prose_slots)
    return ClaimSlotExtraction(evidence_text=evidence, slots=merged, abstained=not merged)


def compare_typed_slots(
    prior: ClaimSlotExtraction,
    candidate: ClaimSlotExtraction,
    *,
    min_confidence: Confidence = _MIN_CONSUMABLE,
) -> TypedSlotDelta | None:
    """Compare confident typed slots. Low-confidence extraction abstains."""
    prior_slots = _consumable(prior.slots, min_confidence)
    candidate_slots = _consumable(candidate.slots, min_confidence)
    if not prior_slots and not candidate_slots:
        return None

    pairs = _align_slots(prior_slots, candidate_slots)
    changes = [
        pair
        for pair in pairs
        if pair[0] is not None and pair[1] is not None and pair[0].identity != pair[1].identity
    ]
    if changes:
        left, right = changes[0]
        assert left is not None and right is not None
        return TypedSlotDelta(
            kind="same_slot_value_change",
            slot=left.slot,
            prior_value=_format_slot(left),
            candidate_value=_format_slot(right),
            confidence=_min_confidence(left.confidence, right.confidence),
            reason=f"{left.slot} value changed from {_format_slot(left)} to {_format_slot(right)}",
        )

    added = [right for left, right in pairs if left is None and right is not None]
    if added:
        slot = added[0]
        return TypedSlotDelta(
            kind="different_slot_added",
            slot=slot.slot,
            prior_value=None,
            candidate_value=_format_slot(slot),
            confidence="high" if slot.confidence == "high" else "medium",
            reason=f"candidate adds {slot.slot}={_format_slot(slot)}",
        )

    matched = [pair for pair in pairs if pair[0] is not None and pair[1] is not None]
    if matched:
        left, right = matched[0]
        assert left is not None and right is not None
        return TypedSlotDelta(
            kind="same_slot_equivalent",
            slot=left.slot,
            prior_value=_format_slot(left),
            candidate_value=_format_slot(right),
            confidence=_min_confidence(left.confidence, right.confidence),
            reason=f"{left.slot} is unchanged after normalization",
        )
    return None


def typed_slots_as_revision_evidence(
    prior: ClaimSlotExtraction,
    candidate: ClaimSlotExtraction,
) -> TypedSlotDelta | None:
    """Evidence a revision judge may consume. Never forces on abstention or low confidence."""
    delta = compare_typed_slots(prior, candidate)
    if delta is None or delta.kind == "same_slot_equivalent":
        return None
    return delta


def apply_typed_slot_evidence(
    *,
    typed: TypedSlotDelta | None,
    prior_valid_at: str | None = None,
    candidate_valid_at: str | None = None,
) -> RevisionHint | None:
    """Optional revision hint from typed evidence. None keeps the prose judge decision."""
    if typed is None or typed.confidence not in {"high", "medium"}:
        return None
    if typed.kind == "same_slot_value_change":
        if prior_valid_at and candidate_valid_at and candidate_valid_at < prior_valid_at:
            return None
        return "STATE_UPDATE"
    if typed.kind == "different_slot_added":
        return "DETAIL"
    return None


def normalize_numeric_value(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).casefold().strip()
    text = re.sub(r"(?<=\d),(?=\d)", "", text)
    for words, number in sorted(_NUMBER_WORDS.items(), key=lambda item: len(item[0]), reverse=True):
        text = re.sub(rf"\b{re.escape(words)}\b", number, text)
    match = _NUMBER_RE.search(text)
    return match.group("number") if match else text


def normalize_unit(value: str | None) -> str | None:
    if not value:
        return None
    key = unicodedata.normalize("NFKC", value).casefold().strip()
    key = re.sub(r"\s+", " ", key)
    return _UNIT_ALIASES.get(key, value.strip())


def normalize_version(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).strip()
    match = _VERSION_RE.search(text)
    if match:
        return match.group("version").lstrip("vV")
    return text.lstrip("vV")


def normalize_comparator(value: str | None) -> str | None:
    if not value:
        return None
    raw = unicodedata.normalize("NFKC", value).strip()
    return _COMPARATOR_NORMALIZE.get(raw, raw)


def normalize_date(value: str) -> str | None:
    text = unicodedata.normalize("NFKC", value).strip()
    month = _DATE_MONTH.search(text)
    if month:
        raw = month.group(0)
        for pattern in _DATE_PATTERNS:
            try:
                return datetime.strptime(raw.title(), pattern).strftime("%Y-%m-%d")
            except ValueError:
                continue
    ymd = _DATE_YMD.search(text)
    if ymd:
        return f"{int(ymd.group('year')):04d}-{int(ymd.group('month')):02d}-{int(ymd.group('day')):02d}"
    return None


def _extract_structured(
    structured: Mapping[str, Any] | None,
    *,
    entity: str | None,
    valid_at: str | None,
) -> list[TypedClaimSlot]:
    if not structured:
        return []
    slots: list[TypedClaimSlot] = []
    for key, slot_name in _STRUCTURED_SLOT_KEYS.items():
        if key not in structured:
            continue
        parsed = _parse_structured_value(
            slot_name,
            structured[key],
            entity=entity or _as_text(structured.get("entity")),
            valid_at=valid_at or _as_text(structured.get("valid_at")),
            origin="structured",
        )
        if parsed is not None:
            slots.append(parsed)
    return slots


def _extract_value_field(
    value_text: str,
    *,
    entity: str | None,
    valid_at: str | None,
) -> list[TypedClaimSlot]:
    text = (value_text or "").strip()
    if not text:
        return []
    folded = _prepare_text(text)
    slots: list[TypedClaimSlot] = []

    if folded in _INCIDENT_STATUS:
        slots.append(
            _slot(
                "incident_status",
                folded,
                entity=entity,
                valid_at=valid_at,
                origin="value",
                raw_span=text,
            )
        )
        return slots
    availability = _AVAILABILITY.get(folded)
    if availability is not None:
        slots.append(
            _slot(
                "availability",
                availability,
                entity=entity,
                valid_at=valid_at,
                origin="value",
                raw_span=text,
            )
        )
        return slots
    if folded in _SEVERITY:
        slots.append(
            _slot("severity", folded, entity=entity, valid_at=valid_at, origin="value", raw_span=text)
        )
        return slots

    compact = _LIMIT_COMPACT_RE.search(folded)
    if compact:
        slot_name: SlotName = "quota" if folded.startswith("quota") else "limit"
        slots.append(
            _slot(
                slot_name,
                normalize_numeric_value(compact.group("number")),
                unit=normalize_unit(compact.group("unit")),
                qualifiers=("timeout",) if folded.startswith("timeout") else (),
                entity=entity,
                valid_at=valid_at,
                origin="value",
                raw_span=text,
            )
        )

    range_match = _RANGE_RE.search(text)
    if range_match:
        slots.append(
            _slot(
                "affected_version_range",
                normalize_version(range_match.group("version")),
                comparator=normalize_comparator(range_match.group("comparator")),
                entity=entity,
                valid_at=valid_at,
                origin="value",
                raw_span=text,
            )
        )

    version_label = re.search(
        r"\b(?:fixed|minimum|maximum|current)\s+v?(?P<version>\d+(?:\.\d+){1,3})\b",
        folded,
        re.IGNORECASE,
    )
    if version_label:
        qualifier = "fixed" if folded.startswith("fixed") else None
        comparator = None
        if folded.startswith("minimum"):
            comparator = ">="
        elif folded.startswith("maximum"):
            comparator = "<="
        slot_name = "affected_version_range" if comparator else "version"
        slots.append(
            _slot(
                slot_name,
                normalize_version(version_label.group("version")),
                comparator=comparator,
                qualifiers=(qualifier,) if qualifier else (),
                entity=entity,
                valid_at=valid_at,
                origin="value",
                raw_span=text,
            )
        )
    return _dedupe_conflicting(slots)


def _extract_prose(
    text: str,
    *,
    entity: str | None,
    valid_at: str | None,
) -> list[TypedClaimSlot]:
    if not text.strip():
        return []
    prepared = _prepare_text(text)
    slots: list[TypedClaimSlot] = []
    default_entity = entity or _infer_entity(text)
    slots.extend(_extract_price(text, entity=default_entity, valid_at=valid_at))
    slots.extend(_extract_limits(prepared, original=text, entity=default_entity, valid_at=valid_at))
    slots.extend(_extract_ranges(text, entity=default_entity, valid_at=valid_at))
    slots.extend(_extract_versions(text, entity=default_entity, valid_at=valid_at))
    slots.extend(_extract_dates(text, valid_at=valid_at, entity=default_entity))
    slots.extend(_extract_platforms(text, entity=default_entity, valid_at=valid_at))
    slots.extend(_extract_severity_prose(prepared, original=text, entity=default_entity, valid_at=valid_at))
    return _dedupe_conflicting(slots)


def _extract_price(text: str, *, entity: str | None, valid_at: str | None) -> list[TypedClaimSlot]:
    slots: list[TypedClaimSlot] = []
    for match in _PRICE_RE.finditer(text):
        currency = match.group("currency").upper().replace("$", "USD").replace("¥", "JPY").replace("€", "EUR")
        if currency == "USD" or match.group("currency") == "$":
            currency = "USD"
        amount = normalize_numeric_value(match.group("amount"))
        period = match.group("period")
        slots.append(
            _slot(
                "price",
                amount,
                unit=currency if not period else f"{currency}/{period.casefold()}",
                entity=entity,
                valid_at=valid_at,
                origin="prose",
                raw_span=match.group(0),
            )
        )
    return slots


def _extract_limits(
    prepared: str,
    *,
    original: str,
    entity: str | None,
    valid_at: str | None,
) -> list[TypedClaimSlot]:
    if not _LIMIT_HINT.search(prepared):
        return []
    slot_name: SlotName = "quota" if _QUOTA_HINT.search(prepared) else "limit"
    qualifiers: list[str] = []
    if _TIMEOUT_HINT.search(prepared):
        qualifiers.append("timeout")
    if re.search(r"\bupload\b", prepared):
        qualifiers.append("upload")
    if re.search(r"\bdownload\b", prepared):
        qualifiers.append("download")

    matches = list(_LIMIT_UNIT_RE.finditer(prepared))
    if not matches:
        compact = _LIMIT_COMPACT_RE.search(prepared)
        if compact is not None:
            matches = [compact]

    values = {
        (
            normalize_numeric_value(match.group("number")),
            normalize_unit(match.group("unit")),
        )
        for match in matches
    }
    if len(values) != 1:
        detached = _detached_limit(prepared)
        if detached is None:
            return []
        number, unit = detached
    else:
        number, unit = next(iter(values))
    return [
        _slot(
            slot_name,
            number,
            unit=unit,
            qualifiers=tuple(qualifiers),
            entity=entity,
            valid_at=valid_at,
            origin="prose",
            raw_span=original,
            confidence="high",
        )
    ]


_DETACHED_UNIT_RE = re.compile(
    r"\b(?P<unit>per-minute|per\s+minute|per\s+hour|per\s+day|"
    r"requests?\s+per\s+(?:minute|hour|day|15\s+minutes)|"
    r"kb|mb|gb|tb|seconds?|minutes?|hours?|days?)\b",
    re.IGNORECASE,
)


def _detached_limit(prepared: str) -> tuple[str, str | None] | None:
    number_values = tuple(dict.fromkeys(match.group("number") for match in _NUMBER_RE.finditer(prepared)))
    unit_values = tuple(
        dict.fromkeys(normalize_unit(match.group("unit")) for match in _DETACHED_UNIT_RE.finditer(prepared))
    )
    if len(number_values) == 1 and len(unit_values) == 1:
        return number_values[0], unit_values[0]
    return None


def _extract_ranges(text: str, *, entity: str | None, valid_at: str | None) -> list[TypedClaimSlot]:
    slots: list[TypedClaimSlot] = []
    for match in _RANGE_RE.finditer(text):
        comparator = normalize_comparator(match.group("comparator"))
        slots.append(
            _slot(
                "affected_version_range",
                normalize_version(match.group("version")),
                comparator=comparator,
                entity=entity,
                valid_at=valid_at,
                origin="prose",
                raw_span=match.group(0),
            )
        )
    if slots:
        return slots

    word_range = re.search(
        r"(?P<entity>[A-Za-z][\w.+-]*)\s+(?P<words>at\s+least|at\s+most|minimum|maximum|"
        r"greater\s+than|less\s+than|up\s+to)\s+v?(?P<version>\d+(?:\.\d+){0,3})",
        text,
        re.IGNORECASE,
    )
    if word_range:
        comparator = None
        for pattern, symbol in _COMPARATOR_WORDS:
            if pattern.search(word_range.group("words")):
                comparator = symbol
                break
        if comparator:
            slots.append(
                _slot(
                    "affected_version_range",
                    normalize_version(word_range.group("version")),
                    comparator=comparator,
                    entity=entity or word_range.group("entity"),
                    valid_at=valid_at,
                    origin="prose",
                    raw_span=word_range.group(0),
                )
            )
    return slots


def _extract_versions(text: str, *, entity: str | None, valid_at: str | None) -> list[TypedClaimSlot]:
    if _RANGE_RE.search(text):
        return []
    versions = [normalize_version(match.group("version")) for match in _VERSION_RE.finditer(text)]
    unique = tuple(dict.fromkeys(versions))
    if len(unique) != 1:
        toward = re.search(
            r"\b(?:to|fixed in|fix(?:ed)? in)\s+v?(?P<version>\d+(?:\.\d+){1,3})\b",
            text,
            re.IGNORECASE,
        )
        if toward is None:
            return []
        unique = (normalize_version(toward.group("version")),)
    qualifier = ("fixed",) if re.search(r"\bfixed\b", text, re.IGNORECASE) else ()
    return [
        _slot(
            "version",
            unique[0],
            qualifiers=qualifier,
            entity=entity,
            valid_at=valid_at,
            origin="prose",
            raw_span=text,
        )
    ]


def _extract_dates(text: str, *, valid_at: str | None, entity: str | None) -> list[TypedClaimSlot]:
    dates = [normalize_date(match.group(0)) for match in _DATE_MONTH.finditer(text)]
    dates.extend(normalize_date(match.group(0)) for match in _DATE_YMD.finditer(text))
    unique = tuple(dict.fromkeys(date for date in dates if date))
    if len(unique) != 1:
        return []
    slot_name: SlotName = "effective_date"
    if _DEPRECATION_HINT.search(text):
        slot_name = "deprecation_date"
    elif not _EFFECTIVE_HINT.search(text) and not re.search(r"\b(?:on|as of)\b", text, re.IGNORECASE):
        return []
    return [
        _slot(
            slot_name,
            unique[0],
            entity=entity,
            valid_at=valid_at,
            origin="prose",
            raw_span=text,
        )
    ]


def _extract_platforms(text: str, *, entity: str | None, valid_at: str | None) -> list[TypedClaimSlot]:
    slots: list[TypedClaimSlot] = []
    for match in _PLATFORM_RE.finditer(text):
        slots.append(
            _slot(
                "supported_platform",
                match.group("platform").casefold(),
                entity=entity,
                valid_at=valid_at,
                origin="prose",
                raw_span=match.group(0),
            )
        )
    return slots


def _extract_severity_prose(
    prepared: str,
    *,
    original: str,
    entity: str | None,
    valid_at: str | None,
) -> list[TypedClaimSlot]:
    match = re.search(r"\bseverity\s*[:=]?\s*(?P<severity>critical|high|medium|moderate|low)\b", prepared)
    if match is None:
        match = re.search(r"\[(?P<severity>critical|high|medium|moderate|low)\]", prepared)
    if match is None:
        return []
    return [
        _slot(
            "severity",
            match.group("severity"),
            entity=entity,
            valid_at=valid_at,
            origin="prose",
            raw_span=original,
        )
    ]


def _parse_structured_value(
    slot_name: SlotName,
    value: Any,
    *,
    entity: str | None,
    valid_at: str | None,
    origin: ValueOrigin,
) -> TypedClaimSlot | None:
    text = _as_text(value)
    if text is None:
        return None
    comparator = None
    unit = None
    normalized = text
    if slot_name in {"version", "affected_version_range"}:
        range_match = _RANGE_RE.search(text)
        if range_match:
            normalized = normalize_version(range_match.group("version"))
            comparator = normalize_comparator(range_match.group("comparator"))
        else:
            normalized = normalize_version(text)
    elif slot_name in {"limit", "quota", "price"}:
        prepared = _prepare_text(text)
        unit_match = _LIMIT_UNIT_RE.search(prepared) or _LIMIT_COMPACT_RE.search(prepared)
        if unit_match:
            normalized = normalize_numeric_value(unit_match.group("number"))
            unit = normalize_unit(unit_match.group("unit"))
        else:
            normalized = normalize_numeric_value(text)
        if slot_name == "price":
            price = _PRICE_RE.search(text)
            if price:
                currency = price.group("currency").upper().replace("$", "USD")
                normalized = normalize_numeric_value(price.group("amount"))
                unit = currency if currency != "$" else "USD"
    elif slot_name in {"effective_date", "deprecation_date"}:
        dated = normalize_date(text)
        if dated is None:
            return None
        normalized = dated
    elif slot_name == "severity":
        folded = text.casefold()
        if folded not in _SEVERITY:
            return None
        normalized = folded
    elif slot_name == "incident_status":
        normalized = text.casefold()
    elif slot_name in {"availability", "status"}:
        normalized = _AVAILABILITY.get(text.casefold(), text.casefold())
    return _slot(
        slot_name,
        normalized,
        unit=unit,
        comparator=comparator,
        entity=entity,
        valid_at=valid_at,
        origin=origin,
        raw_span=text,
        confidence="high",
    )


def _merge_authoritative(
    structured: Sequence[TypedClaimSlot],
    value_slots: Sequence[TypedClaimSlot],
    prose: Sequence[TypedClaimSlot],
) -> tuple[TypedClaimSlot, ...]:
    by_slot: dict[SlotName, TypedClaimSlot] = {}
    for group in (prose, value_slots, structured):
        for slot in group:
            existing = by_slot.get(slot.slot)
            by_slot[slot.slot] = _overlay_slot(slot, existing) if existing else slot
    return tuple(by_slot[name] for name in sorted(by_slot, key=str))


def _overlay_slot(preferred: TypedClaimSlot, fallback: TypedClaimSlot) -> TypedClaimSlot:
    return _slot(
        preferred.slot,
        preferred.value,
        unit=preferred.unit or fallback.unit,
        comparator=preferred.comparator or fallback.comparator,
        qualifiers=tuple(dict.fromkeys((*preferred.qualifiers, *fallback.qualifiers))),
        entity=preferred.entity or fallback.entity,
        valid_at=preferred.valid_at or fallback.valid_at,
        origin=preferred.origin,
        raw_span=preferred.raw_span,
        confidence=preferred.confidence,
    )


def _dedupe_conflicting(slots: Sequence[TypedClaimSlot]) -> list[TypedClaimSlot]:
    grouped: dict[SlotName, list[TypedClaimSlot]] = {}
    for slot in slots:
        grouped.setdefault(slot.slot, []).append(slot)
    kept: list[TypedClaimSlot] = []
    for items in grouped.values():
        identities = {item.identity for item in items}
        if len(identities) != 1:
            continue
        kept.append(items[0])
    return kept


def _align_slots(
    prior: Sequence[TypedClaimSlot],
    candidate: Sequence[TypedClaimSlot],
) -> list[tuple[TypedClaimSlot | None, TypedClaimSlot | None]]:
    pairs: list[tuple[TypedClaimSlot | None, TypedClaimSlot | None]] = []
    used_candidate: set[int] = set()
    for left in prior:
        match_index = _best_match(left, candidate, used_candidate)
        if match_index is None:
            pairs.append((left, None))
            continue
        used_candidate.add(match_index)
        pairs.append((left, candidate[match_index]))
    for index, right in enumerate(candidate):
        if index not in used_candidate:
            pairs.append((None, right))
    return pairs


def _best_match(
    left: TypedClaimSlot,
    candidate: Sequence[TypedClaimSlot],
    used: set[int],
) -> int | None:
    exact = [
        index
        for index, right in enumerate(candidate)
        if index not in used
        and right.slot == left.slot
        and _entity_key(right.entity) == _entity_key(left.entity)
        and _entity_key(left.entity)
    ]
    if len(exact) == 1:
        return exact[0]
    same_slot = [
        index
        for index, right in enumerate(candidate)
        if index not in used and right.slot == left.slot
    ]
    if len(same_slot) == 1:
        right = candidate[same_slot[0]]
        left_entity = _entity_key(left.entity)
        right_entity = _entity_key(right.entity)
        if left_entity and right_entity and left_entity != right_entity:
            return None
        return same_slot[0]
    return None


def _consumable(slots: Sequence[TypedClaimSlot], min_confidence: Confidence) -> tuple[TypedClaimSlot, ...]:
    minimum = _CONFIDENCE_RANK[min_confidence]
    return tuple(slot for slot in slots if _CONFIDENCE_RANK[slot.confidence] >= minimum)


def _min_confidence(left: Confidence, right: Confidence) -> Literal["high", "medium"]:
    return "high" if left == "high" and right == "high" else "medium"


def _format_slot(slot: TypedClaimSlot) -> str:
    prefix = f"{slot.comparator}" if slot.comparator else ""
    unit = f" {slot.unit}" if slot.unit else ""
    return f"{prefix}{slot.value}{unit}".strip()


def _slot(
    slot: SlotName,
    value: str,
    *,
    unit: str | None = None,
    comparator: str | None = None,
    qualifiers: tuple[str, ...] = (),
    entity: str | None,
    valid_at: str | None,
    origin: ValueOrigin,
    raw_span: str,
    confidence: Confidence = "high",
) -> TypedClaimSlot:
    return TypedClaimSlot(
        entity=_clean_entity(entity),
        slot=slot,
        value=value,
        unit=unit,
        comparator=normalize_comparator(comparator),
        qualifiers=qualifiers,
        valid_at=valid_at,
        confidence=confidence,
        origin=origin,
        raw_span=raw_span,
    )


def _infer_entity(text: str) -> str | None:
    folded = text.casefold()
    for product in _PRODUCTS:
        if product in folded:
            return product
    return None


def _entity_key(entity: str | None) -> str:
    if not entity:
        return ""
    folded = unicodedata.normalize("NFKC", entity).casefold().strip()
    return _ENTITY_ALIASES.get(folded, folded)


def _clean_entity(entity: str | None) -> str | None:
    if not entity:
        return None
    text = entity.strip()
    return text or None


def _prepare_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).casefold()
    text = re.sub(r"(?<=\d),(?=\d)", "", text)
    for words, number in sorted(_NUMBER_WORDS.items(), key=lambda item: len(item[0]), reverse=True):
        text = re.sub(rf"\b{re.escape(words)}\b", number, text)
    return text


def _unique_text(*parts: str) -> str:
    seen: list[str] = []
    for part in parts:
        text = (part or "").strip()
        if text and text not in seen:
            seen.append(text)
    return "\n".join(seen)


def _as_text(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else str(value)
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return None
