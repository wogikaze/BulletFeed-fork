"""Typed change candidates from aligned Web sections (#62 / Source-06).

Consumes #61 normalized documents and alignments. Change extraction itself
does not write Observations or Claims; #63 ingest does that through the
ledger. Does not start a renderer (#64). generic_web stays discovery-only.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal

from app.services.claim_semantics import canonicalize_text
from app.services.claim_slots import (
    compare_typed_slots,
    extract_claim_slots,
    normalize_date,
)
from app.services.source_catalog import SourceKind, source_allows_claim_evidence
from app.services.web_normalize import (
    ALIGNER_VERSION,
    DocumentAlignment,
    NormalizedBlock,
    NormalizedDocument,
    SectionAlignment,
    SourceLocator,
    align_normalized_documents,
    normalize_web_snapshot,
)
from app.services.web_snapshots import WebSnapshot

CHANGE_EXTRACTOR_VERSION = "web-changes-v1"
CHANGESET_ID_PREFIX = "chg_"
CANDIDATE_ID_PREFIX = "cand_"
TEMPLATE_SUPPRESS_MIN_PAGES = 3
TYPO_MAX_EDIT_DISTANCE = 2
BLOCK_SIMILARITY_MIN = 0.50
LOW_CONFIDENCE_MAX = 0.60

ChangeKind = Literal[
    "text_addition",
    "text_removal",
    "text_rewrite",
    "numeric_change",
    "version_change",
    "date_deadline_change",
    "price_limit_change",
    "status_availability_change",
    "table_list_row_change",
    "link_target_change",
    "ambiguous_change",
    "non_meaningful",
]
BlockOperation = Literal["insert", "update", "delete"]
ConfidenceLabel = Literal["high", "medium", "low"]

CHANGE_KINDS: tuple[ChangeKind, ...] = (
    "text_addition",
    "text_removal",
    "text_rewrite",
    "numeric_change",
    "version_change",
    "date_deadline_change",
    "price_limit_change",
    "status_availability_change",
    "table_list_row_change",
    "link_target_change",
    "ambiguous_change",
    "non_meaningful",
)

_PRICE_LIMIT_SLOTS = frozenset({"price", "limit", "quota"})
_VERSION_SLOTS = frozenset({"version", "affected_version_range"})
_DATE_SLOTS = frozenset({"effective_date", "deprecation_date"})
_STATUS_SLOTS = frozenset({"availability", "status", "incident_status"})
_TABLE_LIST_KINDS = frozenset({"table", "list"})
_TOKEN_RE = re.compile(r"[0-9A-Za-z\u3040-\u30ff\u3400-\u9fff]+")
_HREF_RE = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_ANCHOR_RE = re.compile(
    r"""<a\b[^>]*href\s*=\s*["']([^"']+)["'][^>]*>(.*?)</a>""",
    re.IGNORECASE | re.DOTALL,
)
_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_DATE_MONTH = re.compile(
    r"\b(?P<month>january|february|march|april|may|june|july|august|september|october|"
    r"november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)"
    r"\s+(?P<day>\d{1,2}),\s+(?P<year>\d{4})\b",
    re.IGNORECASE,
)
_DATE_YMD = re.compile(r"\b(?P<year>\d{4})[-/](?P<month>\d{1,2})[-/](?P<day>\d{1,2})\b")
_STATUS_PHRASES: tuple[tuple[str, str], ...] = (
    ("not available", "unavailable"),
    ("not supported", "unsupported"),
    ("generally available", "available"),
    ("unavailable", "unavailable"),
    ("unsupported", "unsupported"),
    ("available", "available"),
    ("supported", "supported"),
    ("deprecated", "deprecated"),
    ("withdrawn", "withdrawn"),
    ("end of life", "eol"),
    ("retired", "eol"),
)
_SLOT_KIND: dict[str, ChangeKind] = {
    "price": "price_limit_change",
    "limit": "price_limit_change",
    "quota": "price_limit_change",
    "version": "version_change",
    "affected_version_range": "version_change",
    "effective_date": "date_deadline_change",
    "deprecation_date": "date_deadline_change",
    "availability": "status_availability_change",
    "status": "status_availability_change",
    "incident_status": "status_availability_change",
}


class WebChangeError(ValueError):
    """Raised when change candidates cannot be produced from aligned sections."""


class ChangeSetImmutabilityError(ValueError):
    """Raised when a caller attempts to mutate a stored change set."""


@dataclass(frozen=True)
class EvidenceSpan:
    """Old or new evidence, with the raw locator from #61 preserved."""

    snapshot_id: str
    section_id: str | None
    block_id: str | None
    text: str
    locator: SourceLocator


@dataclass(frozen=True)
class ChangeCandidate:
    candidate_id: str
    change_kind: ChangeKind
    operation: BlockOperation
    confidence: float
    confidence_label: ConfidenceLabel
    reason: str
    section_id: str | None
    left_section_id: str | None
    right_section_id: str | None
    left_block_id: str | None
    right_block_id: str | None
    old_span: EvidenceSpan | None
    new_span: EvidenceSpan | None
    old_value: str | None
    new_value: str | None
    extractor_version: str
    alignment_status: str
    suppressed: bool = False
    suppress_reason: str | None = None
    abstain_for_semantics: bool = False

    @property
    def meaningful(self) -> bool:
        return self.change_kind != "non_meaningful" and not self.suppressed


@dataclass(frozen=True)
class ChangeSet:
    changeset_id: str
    left_document_id: str
    right_document_id: str
    canonical_url: str
    extractor_version: str
    aligner_version: str
    candidates: tuple[ChangeCandidate, ...]
    rejected: bool = False
    reject_reason: str | None = None

    @property
    def meaningful_candidates(self) -> tuple[ChangeCandidate, ...]:
        return tuple(item for item in self.candidates if item.meaningful)

    @property
    def downstream_candidates(self) -> tuple[ChangeCandidate, ...]:
        """Keep low-confidence rows; drop formatting-only noise."""
        return tuple(item for item in self.candidates if item.change_kind != "non_meaningful")


def generic_web_allows_claim_evidence() -> bool:
    """Change candidates are not Claims. generic_web remains discovery-only."""
    return source_allows_claim_evidence(SourceKind.GENERIC_WEB.value)


def changeset_id_for(
    left_document_id: str,
    right_document_id: str,
    *,
    extractor_version: str = CHANGE_EXTRACTOR_VERSION,
) -> str:
    material = f"{left_document_id}\n{right_document_id}\n{extractor_version}"
    return f"{CHANGESET_ID_PREFIX}{hashlib.sha256(material.encode()).hexdigest()}"


def extract_web_snapshot_changes(left: WebSnapshot, right: WebSnapshot) -> ChangeSet:
    """Normalize, align, then type insert/update/delete of factual blocks."""
    left_doc = normalize_web_snapshot(left)
    right_doc = normalize_web_snapshot(right)
    return extract_web_changes(
        left_doc,
        right_doc,
        left_raw=_decode_snapshot_text(left),
        right_raw=_decode_snapshot_text(right),
    )


def extract_web_changes(
    left: NormalizedDocument,
    right: NormalizedDocument,
    *,
    alignment: DocumentAlignment | None = None,
    left_raw: str | None = None,
    right_raw: str | None = None,
) -> ChangeSet:
    """Produce versioned, explainable change candidates from aligned sections."""
    changeset_id = changeset_id_for(left.document_id, right.document_id)
    if left.rejected or right.rejected:
        return _rejected_changeset(
            changeset_id,
            left,
            right,
            reason="rejected_document",
        )
    aligned = alignment or align_normalized_documents(left, right)
    if aligned.rejected:
        return _rejected_changeset(
            changeset_id,
            left,
            right,
            reason=aligned.reject_reason or "rejected_alignment",
        )

    left_sections = {section.section_id: section for section in left.sections}
    right_sections = {section.section_id: section for section in right.sections}
    candidates: list[ChangeCandidate] = []
    for pair in aligned.pairs:
        candidates.extend(
            _candidates_for_pair(
                left,
                right,
                pair,
                left_sections,
                right_sections,
                left_raw=left_raw,
                right_raw=right_raw,
            )
        )
    return ChangeSet(
        changeset_id=changeset_id,
        left_document_id=left.document_id,
        right_document_id=right.document_id,
        canonical_url=left.canonical_url,
        extractor_version=CHANGE_EXTRACTOR_VERSION,
        aligner_version=aligned.aligner_version or ALIGNER_VERSION,
        candidates=tuple(candidates),
    )


def suppress_template_duplicates(
    changesets: Sequence[ChangeSet],
    *,
    min_pages: int = TEMPLATE_SUPPRESS_MIN_PAGES,
) -> tuple[ChangeSet, ...]:
    """Mark near-duplicate template edits. Never deletes raw snapshots or docs."""
    urls_by_signature: dict[str, set[str]] = {}
    for changeset in changesets:
        for candidate in changeset.candidates:
            if candidate.change_kind == "non_meaningful":
                continue
            urls_by_signature.setdefault(_template_signature(candidate), set()).add(
                changeset.canonical_url
            )
    hot = {
        signature
        for signature, urls in urls_by_signature.items()
        if len(urls) >= min_pages
    }
    if not hot:
        return tuple(changesets)

    updated: list[ChangeSet] = []
    for changeset in changesets:
        rewritten = []
        for candidate in changeset.candidates:
            if _template_signature(candidate) in hot and candidate.change_kind != "non_meaningful":
                rewritten.append(
                    replace(
                        candidate,
                        suppressed=True,
                        suppress_reason="near_duplicate_template_edit",
                    )
                )
            else:
                rewritten.append(candidate)
        updated.append(replace(changeset, candidates=tuple(rewritten)))
    return tuple(updated)


def classify_text_change(
    old_text: str | None,
    new_text: str | None,
    *,
    block_kind: str = "paragraph",
    old_hrefs: tuple[str, ...] = (),
    new_hrefs: tuple[str, ...] = (),
) -> tuple[ChangeKind, float, str, str | None, str | None]:
    """Classify one factual block pair. Public for guard / noise unit tests."""
    if old_text is None and new_text is None:
        return "non_meaningful", 1.0, "empty_pair", None, None
    if old_text is None:
        return _classify_one_sided(
            new_text or "",
            operation="insert",
            block_kind=block_kind,
            hrefs=new_hrefs,
        )
    if new_text is None:
        return _classify_one_sided(
            old_text,
            operation="delete",
            block_kind=block_kind,
            hrefs=old_hrefs,
        )
    return _classify_update(
        old_text,
        new_text,
        block_kind=block_kind,
        old_hrefs=old_hrefs,
        new_hrefs=new_hrefs,
    )


class ChangeSetStore:
    """File-backed immutable store. Never writes into snapshot/normalized dirs."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, changeset: ChangeSet) -> ChangeSet:
        existing = self.get(changeset.changeset_id)
        if existing is not None:
            if existing != changeset:
                raise ChangeSetImmutabilityError(
                    f"refusing to mutate stored changeset {changeset.changeset_id}"
                )
            return existing
        directory = self.root / changeset.changeset_id
        tmp = self.root / f".tmp-{changeset.changeset_id}-{secrets.token_hex(8)}"
        tmp.mkdir(parents=True, exist_ok=False)
        try:
            (tmp / "changeset.json").write_text(_encode_changeset(changeset), encoding="utf-8")
            os.replace(tmp, directory)
        except Exception:
            _rmtree(tmp)
            raise
        return changeset

    def get(self, changeset_id: str) -> ChangeSet | None:
        path = self.root / changeset_id / "changeset.json"
        if not path.is_file():
            return None
        return _decode_changeset(json.loads(path.read_text(encoding="utf-8")))

    def list_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                path.name
                for path in self.root.iterdir()
                if path.is_dir() and path.name.startswith(CHANGESET_ID_PREFIX)
            )
        )


def _rejected_changeset(
    changeset_id: str,
    left: NormalizedDocument,
    right: NormalizedDocument,
    *,
    reason: str,
) -> ChangeSet:
    return ChangeSet(
        changeset_id=changeset_id,
        left_document_id=left.document_id,
        right_document_id=right.document_id,
        canonical_url=left.canonical_url,
        extractor_version=CHANGE_EXTRACTOR_VERSION,
        aligner_version=ALIGNER_VERSION,
        candidates=(),
        rejected=True,
        reject_reason=reason,
    )


def _candidates_for_pair(
    left: NormalizedDocument,
    right: NormalizedDocument,
    pair: SectionAlignment,
    left_sections: dict[str, Any],
    right_sections: dict[str, Any],
    *,
    left_raw: str | None,
    right_raw: str | None,
) -> list[ChangeCandidate]:
    left_section = left_sections.get(pair.left_section_id) if pair.left_section_id else None
    right_section = right_sections.get(pair.right_section_id) if pair.right_section_id else None
    left_blocks = _factual_blocks(left_section.blocks) if left_section is not None else ()
    right_blocks = _factual_blocks(right_section.blocks) if right_section is not None else ()
    matches = _align_blocks(left_blocks, right_blocks)
    candidates: list[ChangeCandidate] = []
    for old_block, new_block in matches:
        candidate = _candidate_from_blocks(
            left,
            right,
            pair,
            old_block,
            new_block,
            left_raw=left_raw,
            right_raw=right_raw,
        )
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def _candidate_from_blocks(
    left: NormalizedDocument,
    right: NormalizedDocument,
    pair: SectionAlignment,
    old_block: NormalizedBlock | None,
    new_block: NormalizedBlock | None,
    *,
    left_raw: str | None,
    right_raw: str | None,
) -> ChangeCandidate | None:
    old_text = old_block.text if old_block is not None else None
    new_text = new_block.text if new_block is not None else None
    block_kind = (new_block or old_block).kind if (new_block or old_block) else "paragraph"
    old_hrefs = _block_hrefs(old_block, left_raw, old_text or "")
    new_hrefs = _block_hrefs(new_block, right_raw, new_text or "")
    if old_text == new_text and old_text is not None and old_hrefs == new_hrefs:
        return None
    kind, confidence, reason, old_value, new_value = classify_text_change(
        old_text,
        new_text,
        block_kind=block_kind,
        old_hrefs=old_hrefs,
        new_hrefs=new_hrefs,
    )
    if pair.status == "uncertain" and kind != "non_meaningful":
        confidence = round(min(confidence, confidence * 0.85), 4)
        reason = f"{reason}; uncertain_section_alignment"
    operation: BlockOperation
    if old_block is None:
        operation = "insert"
    elif new_block is None:
        operation = "delete"
    else:
        operation = "update"
    if kind == "non_meaningful" and old_text is None:
        return None
    if kind == "non_meaningful" and new_text is None:
        return None
    section_id = _section_identity(pair)
    abstain = kind == "ambiguous_change" or confidence <= LOW_CONFIDENCE_MAX
    label = _confidence_label(confidence)
    if pair.status == "uncertain" and kind != "non_meaningful":
        abstain = True
        if label == "high":
            label = "medium"
    candidate_id = _candidate_id(
        left.document_id,
        right.document_id,
        pair.left_section_id,
        pair.right_section_id,
        old_block.block_id if old_block else None,
        new_block.block_id if new_block else None,
        kind,
        operation,
    )
    return ChangeCandidate(
        candidate_id=candidate_id,
        change_kind=kind,
        operation=operation,
        confidence=confidence,
        confidence_label=label,
        reason=reason,
        section_id=section_id,
        left_section_id=pair.left_section_id,
        right_section_id=pair.right_section_id,
        left_block_id=old_block.block_id if old_block else None,
        right_block_id=new_block.block_id if new_block else None,
        old_span=_span(left.snapshot_id, pair.left_section_id, old_block, left_raw, old_hrefs),
        new_span=_span(right.snapshot_id, pair.right_section_id, new_block, right_raw, new_hrefs),
        old_value=old_value,
        new_value=new_value,
        extractor_version=CHANGE_EXTRACTOR_VERSION,
        alignment_status=pair.status,
        abstain_for_semantics=abstain,
    )


def _classify_one_sided(
    text: str,
    *,
    operation: Literal["insert", "delete"],
    block_kind: str,
    hrefs: tuple[str, ...],
) -> tuple[ChangeKind, float, str, str | None, str | None]:
    typed = _typed_from_text(text)
    if typed is not None:
        kind, value, reason = typed
        verb = "inserted" if operation == "insert" else "removed"
        old_value = value if operation == "delete" else None
        new_value = value if operation == "insert" else None
        return kind, 0.9, f"{verb}_{reason}", old_value, new_value
    if hrefs:
        value = " | ".join(hrefs)
        return (
            "link_target_change",
            0.86,
            f"{operation}_link_target",
            value if operation == "delete" else None,
            value if operation == "insert" else None,
        )
    if block_kind in _TABLE_LIST_KINDS:
        return (
            "table_list_row_change",
            0.88,
            f"{operation}_table_or_list_block",
            text if operation == "delete" else None,
            text if operation == "insert" else None,
        )
    kind: ChangeKind = "text_addition" if operation == "insert" else "text_removal"
    return kind, 0.88, f"{operation}_factual_block", None, None


def _classify_update(
    old_text: str,
    new_text: str,
    *,
    block_kind: str,
    old_hrefs: tuple[str, ...],
    new_hrefs: tuple[str, ...],
) -> tuple[ChangeKind, float, str, str | None, str | None]:
    hrefs_changed = old_hrefs != new_hrefs and (old_hrefs or new_hrefs)
    collapsed_equal = _collapse_ws(old_text) == _collapse_ws(new_text)
    folded_old = unicodedata.normalize("NFKC", _collapse_ws(old_text)).casefold()
    folded_new = unicodedata.normalize("NFKC", _collapse_ws(new_text)).casefold()
    casefold_equal = folded_old == folded_new
    if collapsed_equal and hrefs_changed:
        return (
            "link_target_change",
            0.9,
            "link_or_target_changed",
            " | ".join(old_hrefs) or None,
            " | ".join(new_hrefs) or None,
        )
    if collapsed_equal:
        return (
            "non_meaningful",
            1.0,
            "whitespace_or_formatting_only",
            None,
            None,
        )
    if casefold_equal and not hrefs_changed:
        return "non_meaningful", 1.0, "case_or_unicode_formatting_only", None, None

    old_canon = canonicalize_text(old_text)
    new_canon = canonicalize_text(new_text)
    old_dates_raw = _date_raws(old_text)
    new_dates_raw = _date_raws(new_text)
    old_dates = _date_norms(old_dates_raw)
    new_dates = _date_norms(new_dates_raw)
    old_status = _status_label(old_text)
    new_status = _status_label(new_text)
    old_numbers = _non_version_numbers(old_canon)
    new_numbers = _non_version_numbers(new_canon)

    guards = _guard_hits(
        old_canon,
        new_canon,
        old_dates,
        new_dates,
        old_status,
        new_status,
        hrefs_changed,
        old_numbers,
        new_numbers,
    )

    slot_kind, slot_old, slot_new, slot_reason = _slot_change(old_text, new_text)
    if slot_kind is not None:
        return slot_kind, 0.94, slot_reason, slot_old, slot_new

    if old_canon.versions != new_canon.versions and (old_canon.versions or new_canon.versions):
        return (
            "version_change",
            0.93,
            "version_identifiers_changed",
            _join(old_canon.versions) or _raw_versions(old_text),
            _join(new_canon.versions) or _raw_versions(new_text),
        )
    if old_dates != new_dates and (old_dates or new_dates):
        return (
            "date_deadline_change",
            0.93,
            "date_or_deadline_changed",
            " | ".join(old_dates_raw) or _join(old_dates),
            " | ".join(new_dates_raw) or _join(new_dates),
        )
    if old_status != new_status and (old_status or new_status):
        return (
            "status_availability_change",
            0.92,
            "status_or_availability_changed",
            old_status,
            new_status,
        )
    if old_numbers != new_numbers and (old_numbers or new_numbers):
        return (
            "numeric_change",
            0.92,
            "numeric_facts_changed",
            _join(old_numbers) or old_text,
            _join(new_numbers) or new_text,
        )
    if old_canon.negated != new_canon.negated:
        return (
            "text_rewrite",
            0.9,
            "negation_or_polarity_changed",
            old_text,
            new_text,
        )
    if hrefs_changed:
        return (
            "link_target_change",
            0.9,
            "link_or_target_changed",
            " | ".join(old_hrefs) or None,
            " | ".join(new_hrefs) or None,
        )
    if block_kind in _TABLE_LIST_KINDS and _rows(old_text) != _rows(new_text):
        return (
            "table_list_row_change",
            0.9,
            "table_or_list_rows_changed",
            old_text,
            new_text,
        )

    if not guards and _is_typo_or_punct(old_text, new_text, old_canon, new_canon):
        return "non_meaningful", 0.86, "typo_or_punctuation_only", None, None

    if old_canon.tokens == new_canon.tokens:
        return "non_meaningful", 0.9, "canonical_tokens_equivalent", None, None

    overlap = _token_overlap(old_canon.tokens, new_canon.tokens)
    if overlap >= 0.72:
        return "text_rewrite", 0.74, "substantial_prose_rewrite", None, None
    if overlap <= 0.20:
        return (
            "ambiguous_change",
            0.42,
            "low_overlap_untyped_rewrite_abstain",
            None,
            None,
        )
    return "ambiguous_change", 0.48, "untyped_prose_change_abstain", None, None


def _typed_from_text(text: str) -> tuple[ChangeKind, str, str] | None:
    extraction = extract_claim_slots(text, detail_text=text)
    for slot in extraction.slots:
        kind = _SLOT_KIND.get(slot.slot)
        if kind is not None:
            return kind, slot.raw_span or slot.value, f"{slot.slot}_slot"
    status = _status_label(text)
    if status is not None:
        return "status_availability_change", status, "availability_phrase"
    dates = _date_raws(text)
    if dates:
        return "date_deadline_change", " | ".join(dates), "date_token"
    canon = canonicalize_text(text)
    if canon.versions:
        return "version_change", _join(canon.versions) or text, "version_token"
    if canon.numbers:
        return "numeric_change", _join(canon.numbers) or text, "numeric_token"
    return None


def _slot_change(
    old_text: str,
    new_text: str,
) -> tuple[ChangeKind | None, str | None, str | None, str]:
    prior = extract_claim_slots(old_text, detail_text=old_text)
    candidate = extract_claim_slots(new_text, detail_text=new_text)
    delta = compare_typed_slots(prior, candidate)
    if delta is None:
        return None, None, None, ""
    kind = _SLOT_KIND.get(delta.slot)
    if kind is None:
        return None, None, None, ""
    if delta.kind == "same_slot_equivalent":
        return None, None, None, ""
    old_raw = _raw_for_slot(prior, delta.slot, delta.prior_value)
    new_raw = _raw_for_slot(candidate, delta.slot, delta.candidate_value)
    return kind, old_raw, new_raw, delta.reason


def _raw_for_slot(extraction: Any, slot_name: str, formatted: str | None) -> str | None:
    matches = extraction.slots_named(slot_name)
    if matches:
        return matches[0].raw_span or matches[0].value
    return formatted


def _non_version_numbers(canon: Any) -> tuple[str, ...]:
    fragments = set(canon.versions)
    for version in canon.versions:
        fragments.update(re.findall(r"\d+(?:\.\d+)?", version))
    return tuple(number for number in canon.numbers if number not in fragments)


def _guard_hits(
    old_canon: Any,
    new_canon: Any,
    old_dates: tuple[str, ...],
    new_dates: tuple[str, ...],
    old_status: str | None,
    new_status: str | None,
    hrefs_changed: bool,
    old_numbers: tuple[str, ...],
    new_numbers: tuple[str, ...],
) -> bool:
    if old_canon.versions != new_canon.versions and (old_canon.versions or new_canon.versions):
        return True
    if old_numbers != new_numbers and (old_numbers or new_numbers):
        return True
    if old_canon.negated != new_canon.negated:
        return True
    if old_dates != new_dates and (old_dates or new_dates):
        return True
    if old_status != new_status and (old_status or new_status):
        return True
    return hrefs_changed


def _is_typo_or_punct(old_text: str, new_text: str, old_canon: Any, new_canon: Any) -> bool:
    if set(old_canon.tokens) == set(new_canon.tokens):
        return True
    folded_old = unicodedata.normalize("NFKC", _collapse_ws(old_text)).casefold()
    folded_new = unicodedata.normalize("NFKC", _collapse_ws(new_text)).casefold()
    if _edit_distance(folded_old, folded_new) <= TYPO_MAX_EDIT_DISTANCE:
        return True
    old_tokens = list(old_canon.tokens)
    new_tokens = list(new_canon.tokens)
    if len(old_tokens) == len(new_tokens) and old_tokens and new_tokens:
        diffs = [
            (left, right)
            for left, right in zip(old_tokens, new_tokens, strict=True)
            if left != right
        ]
        if len(diffs) == 1 and _edit_distance(diffs[0][0], diffs[0][1]) <= TYPO_MAX_EDIT_DISTANCE:
            return True
    return False


def _align_blocks(
    left_blocks: tuple[NormalizedBlock, ...],
    right_blocks: tuple[NormalizedBlock, ...],
) -> list[tuple[NormalizedBlock | None, NormalizedBlock | None]]:
    used_left: set[str] = set()
    used_right: set[str] = set()
    pairs: list[tuple[NormalizedBlock | None, NormalizedBlock | None]] = []

    right_by_text: dict[str, list[NormalizedBlock]] = {}
    for block in right_blocks:
        right_by_text.setdefault(_collapse_ws(block.text), []).append(block)
    for left in left_blocks:
        key = _collapse_ws(left.text)
        options = [item for item in right_by_text.get(key, []) if item.block_id not in used_right]
        if len(options) != 1 and key not in right_by_text:
            continue
        if not options:
            continue
        right = options[0]
        pairs.append((left, right))
        used_left.add(left.block_id)
        used_right.add(right.block_id)

    left_by_key = {block.local_key: block for block in left_blocks if block.block_id not in used_left}
    right_by_key = {block.local_key: block for block in right_blocks if block.block_id not in used_right}
    for key, left in left_by_key.items():
        right = right_by_key.get(key)
        if right is None or right.block_id in used_right:
            continue
        pairs.append((left, right))
        used_left.add(left.block_id)
        used_right.add(right.block_id)

    leftover_left = [block for block in left_blocks if block.block_id not in used_left]
    leftover_right = [block for block in right_blocks if block.block_id not in used_right]
    for left in leftover_left:
        candidates = []
        for right in leftover_right:
            if right.block_id in used_right:
                continue
            score = _block_similarity(left, right)
            if score >= BLOCK_SIMILARITY_MIN:
                candidates.append((score, right))
        candidates.sort(key=lambda item: item[0], reverse=True)
        if len(candidates) != 1:
            continue
        right = candidates[0][1]
        reverse = [
            other
            for other in leftover_left
            if other.block_id not in used_left
            and _block_similarity(other, right) >= BLOCK_SIMILARITY_MIN
        ]
        if len(reverse) != 1:
            continue
        pairs.append((left, right))
        used_left.add(left.block_id)
        used_right.add(right.block_id)

    for left in left_blocks:
        if left.block_id not in used_left:
            pairs.append((left, None))
    for right in right_blocks:
        if right.block_id not in used_right:
            pairs.append((None, right))
    return pairs


def _factual_blocks(blocks: tuple[NormalizedBlock, ...]) -> tuple[NormalizedBlock, ...]:
    factual = []
    for block in blocks:
        if block.kind == "heading" and not _heading_has_facts(block.text):
            continue
        factual.append(block)
    return tuple(factual)


def _heading_has_facts(text: str) -> bool:
    canon = canonicalize_text(text)
    return bool(
        canon.numbers
        or canon.versions
        or _date_raws(text)
        or _status_label(text)
        or extract_claim_slots(text, detail_text=text).slots
    )


def _block_hrefs(block: NormalizedBlock | None, raw: str | None, text: str) -> tuple[str, ...]:
    urls = tuple(dict.fromkeys(_URL_RE.findall(text)))
    if not raw:
        return urls
    compact = _collapse_ws(text)
    from_anchors: list[str] = []
    for match in _ANCHOR_RE.finditer(raw):
        inner = _collapse_ws(re.sub(r"<[^>]+>", " ", match.group(2)))
        if inner and compact and inner in compact:
            from_anchors.append(match.group(1))
    region_hrefs: list[str] = []
    if block is not None and block.locator.start_offset is not None:
        start_at = block.locator.start_offset
        end_at = block.locator.end_offset
        end = end_at if end_at is not None else start_at + 240
        start = max(0, start_at - 80)
        region = raw[start : min(len(raw), max(end, start_at) + 80)]
        region_hrefs.extend(_HREF_RE.findall(region))
    return tuple(dict.fromkeys((*from_anchors, *region_hrefs, *urls)))


def _span(
    snapshot_id: str,
    section_id: str | None,
    block: NormalizedBlock | None,
    raw: str | None = None,
    hrefs: tuple[str, ...] = (),
) -> EvidenceSpan | None:
    if block is None:
        return None
    return EvidenceSpan(
        snapshot_id=snapshot_id,
        section_id=section_id,
        block_id=block.block_id,
        text=block.text,
        locator=_locator_for_span(block, raw, hrefs),
    )


def _locator_for_span(
    block: NormalizedBlock,
    raw: str | None,
    hrefs: tuple[str, ...],
) -> SourceLocator:
    locator = block.locator
    if locator.start_offset is not None or not raw:
        return locator
    compact = _collapse_ws(block.text)
    first = compact.split(" ", 1)[0] if compact else ""
    if first:
        index = raw.find(first)
        if index != -1:
            window = raw[index : index + max(len(compact) * 6, 80)]
            return SourceLocator(locator.dom_path, index, index + len(window.strip()))
    if hrefs:
        needle = hrefs[0]
        index = raw.find(needle)
        if index != -1:
            return SourceLocator(locator.dom_path, index, index + len(needle))
    return locator


def _section_identity(pair: SectionAlignment) -> str | None:
    if pair.left_section_id and pair.left_section_id == pair.right_section_id:
        return pair.left_section_id
    return pair.right_section_id or pair.left_section_id


def _candidate_id(
    left_document_id: str,
    right_document_id: str,
    left_section_id: str | None,
    right_section_id: str | None,
    left_block_id: str | None,
    right_block_id: str | None,
    kind: str,
    operation: str,
) -> str:
    material = "\n".join(
        (
            CHANGE_EXTRACTOR_VERSION,
            left_document_id,
            right_document_id,
            left_section_id or "",
            right_section_id or "",
            left_block_id or "",
            right_block_id or "",
            kind,
            operation,
        )
    )
    return f"{CANDIDATE_ID_PREFIX}{hashlib.sha256(material.encode()).hexdigest()}"


def _template_signature(candidate: ChangeCandidate) -> str:
    old = _collapse_ws(candidate.old_span.text) if candidate.old_span else ""
    new = _collapse_ws(candidate.new_span.text) if candidate.new_span else ""
    material = f"{candidate.change_kind}\n{candidate.operation}\n{old}\n{new}"
    return hashlib.sha256(material.encode()).hexdigest()


def _decode_snapshot_text(snapshot: WebSnapshot) -> str:
    try:
        return bytes(snapshot.body).decode("utf-8")
    except UnicodeDecodeError:
        return bytes(snapshot.body).decode("utf-8", errors="replace")


def _date_raws(text: str) -> tuple[str, ...]:
    found = [match.group(0) for match in _DATE_MONTH.finditer(text)]
    found.extend(match.group(0) for match in _DATE_YMD.finditer(text))
    return tuple(found)


def _date_norms(raws: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(norm for raw in raws if (norm := normalize_date(raw))))


def _status_label(text: str) -> str | None:
    folded = unicodedata.normalize("NFKC", text).casefold()
    for phrase, label in _STATUS_PHRASES:
        if phrase in folded:
            return label
    if re.search(r"\beol\b", folded):
        return "eol"
    return None


def _raw_versions(text: str) -> str | None:
    matches = re.findall(r"\bv?\d+(?:\.\d+){1,3}(?:[-+][a-z0-9.-]+)?\b", text, flags=re.IGNORECASE)
    return " | ".join(matches) if matches else None


def _rows(text: str) -> tuple[str, ...]:
    return tuple(line.strip() for line in text.splitlines() if line.strip())


def _block_similarity(left: NormalizedBlock, right: NormalizedBlock) -> float:
    left_tokens = set(_TOKEN_RE.findall(unicodedata.normalize("NFKC", left.text).casefold()))
    right_tokens = set(_TOKEN_RE.findall(unicodedata.normalize("NFKC", right.text).casefold()))
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _token_overlap(left: tuple[str, ...], right: tuple[str, ...]) -> float:
    left_set = set(left)
    right_set = set(right)
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set | right_set)


def _collapse_ws(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _join(values: tuple[str, ...]) -> str | None:
    return " | ".join(values) if values else None


def _confidence_label(confidence: float) -> ConfidenceLabel:
    if confidence >= 0.80:
        return "high"
    if confidence >= 0.60:
        return "medium"
    return "low"


def _edit_distance(left: str, right: str) -> int:
    if left == right:
        return 0
    if abs(len(left) - len(right)) > 8:
        return 99
    previous = list(range(len(right) + 1))
    for i, left_ch in enumerate(left, start=1):
        current = [i]
        for j, right_ch in enumerate(right, start=1):
            insert_cost = current[j - 1] + 1
            delete_cost = previous[j] + 1
            replace_cost = previous[j - 1] + (left_ch != right_ch)
            current.append(min(insert_cost, delete_cost, replace_cost))
        previous = current
    return previous[-1]


def _encode_changeset(changeset: ChangeSet) -> str:
    payload = {
        "changeset_id": changeset.changeset_id,
        "left_document_id": changeset.left_document_id,
        "right_document_id": changeset.right_document_id,
        "canonical_url": changeset.canonical_url,
        "extractor_version": changeset.extractor_version,
        "aligner_version": changeset.aligner_version,
        "rejected": changeset.rejected,
        "reject_reason": changeset.reject_reason,
        "candidates": [_encode_candidate(item) for item in changeset.candidates],
    }
    return json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def _encode_candidate(candidate: ChangeCandidate) -> dict[str, Any]:
    return {
        "candidate_id": candidate.candidate_id,
        "change_kind": candidate.change_kind,
        "operation": candidate.operation,
        "confidence": candidate.confidence,
        "confidence_label": candidate.confidence_label,
        "reason": candidate.reason,
        "section_id": candidate.section_id,
        "left_section_id": candidate.left_section_id,
        "right_section_id": candidate.right_section_id,
        "left_block_id": candidate.left_block_id,
        "right_block_id": candidate.right_block_id,
        "old_span": _encode_span(candidate.old_span),
        "new_span": _encode_span(candidate.new_span),
        "old_value": candidate.old_value,
        "new_value": candidate.new_value,
        "extractor_version": candidate.extractor_version,
        "alignment_status": candidate.alignment_status,
        "suppressed": candidate.suppressed,
        "suppress_reason": candidate.suppress_reason,
        "abstain_for_semantics": candidate.abstain_for_semantics,
    }


def _encode_span(span: EvidenceSpan | None) -> dict[str, Any] | None:
    if span is None:
        return None
    return {
        "snapshot_id": span.snapshot_id,
        "section_id": span.section_id,
        "block_id": span.block_id,
        "text": span.text,
        "locator": {
            "dom_path": span.locator.dom_path,
            "start_offset": span.locator.start_offset,
            "end_offset": span.locator.end_offset,
        },
    }


def _decode_changeset(payload: dict[str, Any]) -> ChangeSet:
    candidates = tuple(_decode_candidate(item) for item in payload.get("candidates", []))
    return ChangeSet(
        changeset_id=str(payload["changeset_id"]),
        left_document_id=str(payload["left_document_id"]),
        right_document_id=str(payload["right_document_id"]),
        canonical_url=str(payload["canonical_url"]),
        extractor_version=str(payload["extractor_version"]),
        aligner_version=str(payload["aligner_version"]),
        candidates=candidates,
        rejected=bool(payload.get("rejected", False)),
        reject_reason=payload.get("reject_reason"),
    )


def _decode_candidate(payload: dict[str, Any]) -> ChangeCandidate:
    return ChangeCandidate(
        candidate_id=str(payload["candidate_id"]),
        change_kind=payload["change_kind"],
        operation=payload["operation"],
        confidence=float(payload["confidence"]),
        confidence_label=payload["confidence_label"],
        reason=str(payload["reason"]),
        section_id=payload.get("section_id"),
        left_section_id=payload.get("left_section_id"),
        right_section_id=payload.get("right_section_id"),
        left_block_id=payload.get("left_block_id"),
        right_block_id=payload.get("right_block_id"),
        old_span=_decode_span(payload.get("old_span")),
        new_span=_decode_span(payload.get("new_span")),
        old_value=payload.get("old_value"),
        new_value=payload.get("new_value"),
        extractor_version=str(payload["extractor_version"]),
        alignment_status=str(payload.get("alignment_status", "")),
        suppressed=bool(payload.get("suppressed", False)),
        suppress_reason=payload.get("suppress_reason"),
        abstain_for_semantics=bool(payload.get("abstain_for_semantics", False)),
    )


def _decode_span(payload: dict[str, Any] | None) -> EvidenceSpan | None:
    if not payload:
        return None
    locator = payload.get("locator") or {}
    return EvidenceSpan(
        snapshot_id=str(payload["snapshot_id"]),
        section_id=payload.get("section_id"),
        block_id=payload.get("block_id"),
        text=str(payload["text"]),
        locator=SourceLocator(
            dom_path=str(locator.get("dom_path", "")),
            start_offset=locator.get("start_offset"),
            end_offset=locator.get("end_offset"),
        ),
    )


def _rmtree(path: Path) -> None:
    if not path.exists():
        return
    if path.is_file():
        path.unlink()
        return
    for child in path.iterdir():
        _rmtree(child)
    path.rmdir()
