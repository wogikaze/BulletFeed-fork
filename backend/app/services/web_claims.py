"""Turn #62 Web change candidates into Observations and optional Claims (#63).

generic_web stays discovery-only. Observations always carry snapshot/section
provenance. Claims are created only for allowlisted official_changelog /
documentation pages that pass source_allows_claim_evidence. Existing
ClaimLedgerStore / judge_revision / coreference remain the semantic authority.
Does not render JavaScript (#64).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from app.database import Database
from app.services.claim_slots import extract_claim_slots
from app.services.feed_projection import project_event_for_audience
from app.services.ledger_projection import LedgerProjector
from app.services.source_catalog import SourceKind, source_allows_claim_evidence
from app.services.source_ingestion import NormalizedObservation, SourceIngestionPipeline
from app.services.source_registry import SourceRegistry, canonicalize_url
from app.services.web_changes import ChangeCandidate, ChangeSet, EvidenceSpan
from app.services.web_snapshots import WebSnapshot
from app.stores.claim_ledger_store import ClaimLedgerStore, LedgerClaim
from app.stores.observation_store import Observation

WEB_CLAIM_INGEST_VERSION = "web-claims-v1"
OFFICIAL_WEB_CLAIM_FAMILIES = frozenset(
    {
        SourceKind.OFFICIAL_CHANGELOG.value,
        SourceKind.DOCUMENTATION.value,
    }
)
_KIND_SLOT = {
    "price_limit_change": "price",
    "version_change": "version",
    "date_deadline_change": "effective_date",
    "status_availability_change": "availability",
    "numeric_change": "limit",
}
_TYPED_SLOTS = frozenset(
    {
        "price",
        "limit",
        "quota",
        "version",
        "effective_date",
        "deprecation_date",
        "availability",
        "status",
    }
)
_CORRECTION_MARKERS = ("corrected", "correction", "errata", "訂正", "修正")


@dataclass(frozen=True)
class WebClaimIngestResult:
    source_type: str
    claim_eligible: bool
    observations: tuple[Observation, ...]
    claims: tuple[LedgerClaim, ...]
    event_ids: tuple[str, ...]
    abstained_candidate_ids: tuple[str, ...]


def generic_web_allows_claim_evidence() -> bool:
    """generic_web remains discovery-only after Observation ingest."""
    return source_allows_claim_evidence(SourceKind.GENERIC_WEB.value)


def official_web_family_allows_claim_evidence(family: str) -> bool:
    """Fail closed: only catalogued official HTML families may back Claims."""
    return family in OFFICIAL_WEB_CLAIM_FAMILIES and source_allows_claim_evidence(family)


def resolve_web_claim_source_type(
    url: str,
    *,
    registry: SourceRegistry | None = None,
    requested_family: str | None = None,
) -> str:
    """Resolve the Observation/Claim family for a page.

    Unregistered or non-official pages stay generic_web. A requested official
    family is honored only when it is catalog-eligible and, if a registry is
    provided, the URL is registered as that family.
    """
    requested = (requested_family or "").strip()
    if requested:
        if official_web_family_allows_claim_evidence(requested):
            if registry is not None:
                endpoint = registry.find_duplicate_endpoint(url, family=requested)
                if endpoint is None:
                    return SourceKind.GENERIC_WEB.value
            return requested
        return SourceKind.GENERIC_WEB.value
    if registry is not None:
        for family in sorted(OFFICIAL_WEB_CLAIM_FAMILIES):
            endpoint = registry.find_duplicate_endpoint(url, family=family)
            if endpoint is not None and official_web_family_allows_claim_evidence(family):
                return family
    return SourceKind.GENERIC_WEB.value


def ingest_web_changeset(
    database: Database,
    changeset: ChangeSet,
    *,
    left_snapshot: WebSnapshot | None = None,
    right_snapshot: WebSnapshot | None = None,
    registry: SourceRegistry | None = None,
    requested_family: str | None = None,
    retrieved_at: str | None = None,
    project: bool = True,
    audience_user_ids: Sequence[str] = (),
    coreference_subject: str | None = None,
    coreference_user_id: str | None = None,
    event_title: str | None = None,
) -> WebClaimIngestResult:
    """Append provenance Observations; mint Claims only when policy allows."""
    source_type = resolve_web_claim_source_type(
        changeset.canonical_url,
        registry=registry,
        requested_family=requested_family,
    )
    claim_eligible = source_allows_claim_evidence(source_type)
    source_key = canonicalize_url(changeset.canonical_url)
    observed_at = (
        retrieved_at
        or (right_snapshot.retrieved_at if right_snapshot is not None else None)
        or (left_snapshot.retrieved_at if left_snapshot is not None else None)
        or ""
    )
    if not observed_at:
        raise ValueError("retrieved_at or a snapshot timestamp is required")

    items: list[NormalizedObservation] = []
    claim_plans: list[tuple[ChangeCandidate, dict[str, Any]]] = []
    abstained: list[str] = []
    for candidate in changeset.downstream_candidates:
        payload = _observation_payload(
            changeset,
            candidate,
            left_snapshot=left_snapshot,
            right_snapshot=right_snapshot,
        )
        items.append(
            NormalizedObservation(
                source_type=source_type,
                source_key=source_key,
                source_observation_id=candidate.candidate_id,
                payload=payload,
                original_url=changeset.canonical_url,
                published_at=observed_at,
            )
        )
        plan = _claim_plan(candidate) if claim_eligible else None
        if plan is None:
            abstained.append(candidate.candidate_id)
        else:
            claim_plans.append((candidate, plan))

    observations = SourceIngestionPipeline(database).ingest_many(
        items,
        retrieved_at=observed_at,
    )
    by_candidate = {item.source_observation_id: item for item in observations}

    claims: list[LedgerClaim] = []
    if claim_eligible and claim_plans:
        ledger = ClaimLedgerStore(database)
        page_title = event_title or _page_title(changeset, right_snapshot or left_snapshot)
        for candidate, plan in claim_plans:
            observation = by_candidate[candidate.candidate_id]
            claim = ledger.ingest(
                observation,
                source_event_id=source_key,
                title=page_title,
                slot=plan["slot"],
                value=plan["value"],
                detail=plan["detail"],
                valid_at=observed_at,
                source_updated_at=observed_at,
                evidence_text=plan["evidence_text"],
                explicit_correction=plan["explicit_correction"],
                coreference_subject=coreference_subject or plan["subject"],
                coreference_user_id=coreference_user_id,
            )
            claims.append(claim)

    event_ids = tuple(dict.fromkeys(claim.event_id for claim in claims))
    if project and event_ids:
        projector = LedgerProjector(database)
        for event_id in event_ids:
            projector.project_event(event_id)
        if audience_user_ids:
            for event_id in event_ids:
                project_event_for_audience(
                    database,
                    event_id=event_id,
                    user_ids=audience_user_ids,
                )
    return WebClaimIngestResult(
        source_type=source_type,
        claim_eligible=claim_eligible,
        observations=observations,
        claims=tuple(claims),
        event_ids=event_ids,
        abstained_candidate_ids=tuple(dict.fromkeys(abstained)),
    )


def _observation_payload(
    changeset: ChangeSet,
    candidate: ChangeCandidate,
    *,
    left_snapshot: WebSnapshot | None,
    right_snapshot: WebSnapshot | None,
) -> dict[str, Any]:
    return {
        "ingest_version": WEB_CLAIM_INGEST_VERSION,
        "changeset_id": changeset.changeset_id,
        "candidate_id": candidate.candidate_id,
        "canonical_url": changeset.canonical_url,
        "change_kind": candidate.change_kind,
        "operation": candidate.operation,
        "reason": candidate.reason,
        "section_id": candidate.section_id,
        "left_section_id": candidate.left_section_id,
        "right_section_id": candidate.right_section_id,
        "left_block_id": candidate.left_block_id,
        "right_block_id": candidate.right_block_id,
        "left_snapshot_id": _snapshot_id(candidate.old_span, left_snapshot),
        "right_snapshot_id": _snapshot_id(candidate.new_span, right_snapshot),
        "old_span": _span_payload(candidate.old_span),
        "new_span": _span_payload(candidate.new_span),
        "old_value": candidate.old_value,
        "new_value": candidate.new_value,
        "extractor_version": candidate.extractor_version,
        "aligner_version": changeset.aligner_version,
        "alignment_status": candidate.alignment_status,
        "abstain_for_semantics": candidate.abstain_for_semantics,
        "suppressed": candidate.suppressed,
        "suppress_reason": candidate.suppress_reason,
    }


def _claim_plan(candidate: ChangeCandidate) -> dict[str, Any] | None:
    if candidate.suppressed or candidate.abstain_for_semantics:
        return None
    if candidate.change_kind in {"ambiguous_change", "non_meaningful", "link_target_change"}:
        return None
    slot = _slot_for(candidate)
    value = _value_for(candidate, slot)
    if not slot or not value:
        return None
    old_value = candidate.old_value
    new_value = candidate.new_value or value
    return {
        "slot": slot,
        "value": value,
        "detail": _detail_for(candidate, old_value, new_value),
        "evidence_text": _evidence_text(candidate),
        "explicit_correction": _looks_like_correction(candidate),
        "subject": _subject_for(candidate),
    }


def _slot_for(candidate: ChangeCandidate) -> str | None:
    text = _candidate_text(candidate)
    extracted = {slot.slot for slot in extract_claim_slots(text, detail_text=text).slots}
    folded = text.casefold()
    if candidate.change_kind == "price_limit_change":
        if "quota" in extracted:
            return "quota"
        if "limit" in extracted or "limit" in candidate.reason or "rate" in folded:
            return "limit"
        if "price" in extracted or "$" in text or "price" in folded:
            return "price"
        return "limit"
    if candidate.change_kind == "date_deadline_change":
        if (
            "deprecation_date" in extracted
            or "deprecat" in folded
            or "eol" in folded
        ):
            return "deprecation_date"
        return "effective_date"
    kind_slot = _KIND_SLOT.get(candidate.change_kind)
    if kind_slot is not None:
        return kind_slot
    if candidate.change_kind in {"text_addition", "text_rewrite", "table_list_row_change"}:
        for slot in extract_claim_slots(text, detail_text=text).slots:
            if slot.slot in _TYPED_SLOTS:
                return slot.slot
    return None


def _value_for(candidate: ChangeCandidate, slot: str | None = None) -> str:
    slot = slot or _slot_for(candidate)
    texts = [
        candidate.new_span.text if candidate.new_span else "",
        _candidate_text(candidate),
    ]
    if slot:
        for text in texts:
            if not text.strip():
                continue
            matches = extract_claim_slots(text, detail_text=text).slots_named(slot)
            if matches:
                return matches[0].value
    if candidate.new_value:
        return candidate.new_value
    if candidate.operation == "delete" and candidate.old_value:
        return candidate.old_value
    if candidate.new_span and candidate.new_span.text.strip():
        return candidate.new_span.text.strip()
    if candidate.old_span and candidate.old_span.text.strip():
        return candidate.old_span.text.strip()
    return ""


def _detail_for(
    candidate: ChangeCandidate,
    old_value: str | None,
    new_value: str | None,
) -> str:
    if old_value and new_value and old_value != new_value:
        return f"{old_value} -> {new_value}"
    if candidate.new_span and candidate.new_span.text.strip():
        return candidate.new_span.text.strip()
    if candidate.old_span and candidate.old_span.text.strip():
        return candidate.old_span.text.strip()
    return new_value or old_value or candidate.reason


def _evidence_text(candidate: ChangeCandidate) -> str:
    parts = [
        f"candidate={candidate.candidate_id}",
        f"kind={candidate.change_kind}",
        f"section={candidate.section_id or ''}",
    ]
    if candidate.old_span is not None:
        parts.append(f"old={_span_ref(candidate.old_span)} text={candidate.old_span.text!r}")
    if candidate.new_span is not None:
        parts.append(f"new={_span_ref(candidate.new_span)} text={candidate.new_span.text!r}")
    if candidate.old_value:
        parts.append(f"old_value={candidate.old_value}")
    if candidate.new_value:
        parts.append(f"new_value={candidate.new_value}")
    return " | ".join(parts)


def _span_ref(span: EvidenceSpan) -> str:
    locator = span.locator
    return (
        f"snapshot={span.snapshot_id} section={span.section_id or ''} "
        f"block={span.block_id or ''} path={locator.dom_path} "
        f"off={locator.start_offset}:{locator.end_offset}"
    )


def _span_payload(span: EvidenceSpan | None) -> dict[str, Any] | None:
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


def _snapshot_id(span: EvidenceSpan | None, snapshot: WebSnapshot | None) -> str | None:
    if span is not None and span.snapshot_id:
        return span.snapshot_id
    if snapshot is not None:
        return snapshot.snapshot_id
    return None


def _looks_like_correction(candidate: ChangeCandidate) -> bool:
    blob = " ".join(
        part
        for part in (
            candidate.reason,
            candidate.new_value,
            candidate.new_span.text if candidate.new_span else None,
        )
        if part
    ).casefold()
    return any(marker in blob for marker in _CORRECTION_MARKERS)


def _subject_for(candidate: ChangeCandidate) -> str:
    return _candidate_text(candidate)[:240]


def _candidate_text(candidate: ChangeCandidate) -> str:
    return " ".join(
        part
        for part in (
            candidate.old_span.text if candidate.old_span else None,
            candidate.new_span.text if candidate.new_span else None,
            candidate.old_value,
            candidate.new_value,
            candidate.reason,
        )
        if part
    )


def _page_title(changeset: ChangeSet, snapshot: WebSnapshot | None) -> str:
    if snapshot is not None:
        html = bytes(snapshot.body).decode("utf-8", errors="replace")
        start = html.lower().find("<title>")
        end = html.lower().find("</title>")
        if start != -1 and end > start:
            title = html[start + 7 : end].strip()
            if title:
                return title
    parsed = urlparse(changeset.canonical_url)
    path = parsed.path.strip("/") or parsed.hostname or changeset.canonical_url
    return path.replace("-", " ").replace("/", " — ")
