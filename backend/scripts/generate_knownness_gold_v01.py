from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.evaluation.knownness_gold import DATASET_VERSION, LABEL_PROTOCOL_VERSION, REQUIRED_FAMILIES
from app.evaluation.label_contract import PROTOCOL_VERSION

ROOT = Path(__file__).resolve().parents[1] / "tests" / "gold" / "knownness" / "v01"
PROVENANCE = (
    "annotator=knownness-gold-v01; protocol=label-protocol-v1; "
    "generated=2026-08-29; kind=synthetic_fixed; issue=55"
)
LABELED_AT = "2026-08-29T14:00:00Z"
BASE_TS = 1_780_000_000

FAMILIES = REQUIRED_FAMILIES

# Two variants per family so each split covers several source families.
# Blind copy uses a disjoint product/id namespace.
PILOT_VARIANTS: tuple[dict[str, str], ...] = (
    {
        "suffix": "a",
        "product": "GitHub Actions",
        "source_family": "statuspage",
        "publisher": "GitHub Status",
        "title": "Actions job start failure",
        "summary": "Newly queued Actions jobs never leave the queued state.",
        "alt_summary": "Workflow runs are failing to start.",
        "detail_summary": (
            "Newly queued Actions jobs never leave the queued state; us-east-1 webhooks are delayed."
        ),
        "correction_summary": (
            "Earlier report was wrong: Actions is operating normally. "
            "The queued-state alarm was a monitor bug."
        ),
    },
    {
        "suffix": "b",
        "product": "Guzzle",
        "source_family": "github_advisory",
        "publisher": "GitHub Advisory Database",
        "title": "Guzzle Referer fragment leak",
        "summary": "Affected Guzzle versions can disclose URI fragments in generated Referer headers.",
        "alt_summary": "Redirects from Guzzle may leak the URL hash through the Referer header.",
        "detail_summary": (
            "Affected Guzzle versions can disclose URI fragments in generated Referer headers "
            "when a 302 follows a URL that includes a hash."
        ),
        "correction_summary": (
            "Correction: Guzzle 7.9.3 is not affected. The fragment leak applies only to 7.4.x."
        ),
    },
)

BLIND_VARIANTS: tuple[dict[str, str], ...] = (
    {
        "suffix": "a",
        "product": "npm registry",
        "source_family": "osv",
        "publisher": "OSV",
        "title": "npm token scope bypass",
        "summary": "A crafted package.json can mint a publish token with a wider scope than granted.",
        "alt_summary": "Publish tokens may escape the requested npm scope.",
        "detail_summary": (
            "A crafted package.json can mint a publish token with a wider scope than granted, "
            "including org-level packages."
        ),
        "correction_summary": (
            "Correction: the scope bypass does not affect granular access tokens created after 2026-03-01."
        ),
    },
    {
        "suffix": "b",
        "product": "React 19",
        "source_family": "github_release",
        "publisher": "React",
        "title": "React 19.1 compiler default",
        "summary": "React 19.1 enables the compiler by default for new apps.",
        "alt_summary": "New React 19.1 applications ship with the compiler turned on.",
        "detail_summary": (
            "React 19.1 enables the compiler by default for new apps and documents a one-line opt-out."
        ),
        "correction_summary": (
            "Correction: the compiler is not default in 19.1. It remains opt-in; the blog post was wrong."
        ),
    },
)

EXTRA_SOURCE_ROTATION = (
    ("rss_atom", "GitHub Blog"),
    ("json_feed", "Status JSON Feed"),
)


@dataclass(frozen=True)
class FamilyPolicy:
    evidence_type: str
    knownness: str
    should_surface: bool
    is_novel_fact: bool
    is_correction: bool
    relation: str
    kinds: tuple[str, ...]
    display: dict[str, Any] | None
    rationale: str


POLICIES: dict[str, FamilyPolicy] = {
    "never_seen": FamilyPolicy(
        "none",
        "new",
        True,
        True,
        False,
        "unseen",
        (),
        None,
        "No knowledge evidence. The fact is new to the user and must surface.",
    ),
    "delivered_not_displayed": FamilyPolicy(
        "delivered",
        "new",
        True,
        True,
        False,
        "same_fact",
        ("delivered",),
        None,
        "Delivery without a viewport exposure is not knowledge. Keep the item unknown.",
    ),
    "briefly_displayed": FamilyPolicy(
        "delivered",
        "new",
        True,
        True,
        False,
        "same_fact",
        ("delivered",),
        {"dwell_ms": 180, "visible_ratio": 0.12, "detail_opened": False},
        "A flash through the viewport fails viewport-exposure-v1, so the user still does not know it.",
    ),
    "meaningfully_displayed": FamilyPolicy(
        "displayed",
        "already_knew",
        False,
        False,
        False,
        "same_fact",
        ("delivered", "displayed"),
        {"dwell_ms": 2400, "visible_ratio": 0.82, "detail_opened": False},
        "Meaningful display is knowledge evidence. Reshowing the same fact is known-but-reshown.",
    ),
    "explicitly_read": FamilyPolicy(
        "read",
        "already_knew",
        False,
        False,
        False,
        "same_fact",
        ("delivered", "displayed", "read"),
        {"dwell_ms": 4000, "visible_ratio": 0.9, "detail_opened": True},
        "The user opened the Event detail. The same fact must not be reshown.",
    ),
    "already_knew": FamilyPolicy(
        "already_knew",
        "already_knew",
        False,
        False,
        False,
        "same_fact",
        ("already_knew",),
        None,
        "Explicit already_knew feedback is high-confidence knowledge. Same-fact reshown is a miss.",
    ),
    "learned_now": FamilyPolicy(
        "learned_now",
        "already_knew",
        False,
        False,
        False,
        "same_fact",
        ("delivered", "displayed", "read", "learned_now"),
        {"dwell_ms": 3200, "visible_ratio": 0.75, "detail_opened": True},
        "The user marked learned_now in BulletFeed. Subsequent same-fact cards are known.",
    ),
    "cross_source_restatement": FamilyPolicy(
        "read",
        "already_knew",
        False,
        False,
        False,
        "equivalent_restatement",
        ("delivered", "displayed", "read"),
        {"dwell_ms": 2800, "visible_ratio": 0.7, "detail_opened": True},
        "Another source restates the same fact. Shared knowledge identity must not treat it as new.",
    ),
    "added_detail": FamilyPolicy(
        "read",
        "new",
        True,
        True,
        False,
        "added_detail",
        ("delivered", "displayed", "read"),
        {"dwell_ms": 2800, "visible_ratio": 0.7, "detail_opened": True},
        "Added factual detail is a new knowledge target even when the parent fact was read.",
    ),
    "correction": FamilyPolicy(
        "read",
        "already_knew",
        True,
        False,
        True,
        "correction",
        ("delivered", "displayed", "read"),
        {"dwell_ms": 2800, "visible_ratio": 0.7, "detail_opened": True},
        "A correction updates a known wrong fact and must surface across the knownness boundary.",
    ),
    "baseline_before_follow": FamilyPolicy(
        "baseline",
        "already_knew",
        False,
        False,
        False,
        "same_fact",
        ("baseline",),
        None,
        "Follow-time baseline marks history already true. It must not flood the feed as unknown.",
    ),
}

KIND_PROVENANCE = {
    "delivered": ("delivery", "low"),
    "displayed": ("display", "medium"),
    "read": ("read", "medium"),
    "already_knew": ("explicit_feedback", "high"),
    "learned_now": ("explicit_feedback", "high"),
    "baseline": ("baseline", "high"),
}


def _prefix(split: str) -> str:
    return "kngp" if split == "pilot" else "kngb"


def _bundle(split: str, family: str) -> str:
    return f"{_prefix(split)}-{family.replace('_', '-')}"


def _source_for(split: str, family: str, variant: dict[str, str]) -> tuple[str, str]:
    if family == "cross_source_restatement":
        extra = EXTRA_SOURCE_ROTATION[0 if variant["suffix"] == "a" else 1]
        return extra
    return variant["source_family"], variant["publisher"]


def _candidate_summary(family: str, variant: dict[str, str]) -> str:
    if family == "cross_source_restatement":
        return variant["alt_summary"]
    if family == "added_detail":
        return variant["detail_summary"]
    if family == "correction":
        return variant["correction_summary"]
    return variant["summary"]


def _build_case(
    *,
    split: str,
    family: str,
    index: int,
    variant: dict[str, str],
    ambiguous: bool = False,
) -> dict[str, Any]:
    policy = POLICIES[family]
    prefix = _prefix(split)
    case_id = f"{prefix}-c-{index:03d}"
    user_id = f"{prefix}-u-{index:03d}"
    item_id = f"{prefix}-i-{index:03d}"
    event_id = f"{prefix}-evt-{index:03d}"
    claim_id = f"{prefix}-cl-{index:03d}"
    prior_claim_id = f"{prefix}-cl-{index:03d}p" if policy.kinds else None
    knowledge_id = f"{prefix}-kn-{index:03d}"
    prior_knowledge_id = knowledge_id
    if family == "added_detail":
        prior_knowledge_id = f"{prefix}-kn-{index:03d}p"
    elif family in {"never_seen"}:
        prior_knowledge_id = None
        prior_claim_id = None
    source_family, publisher = _source_for(split, family, variant)
    evidence: list[dict[str, Any]] = []
    for offset, kind in enumerate(policy.kinds, start=1):
        provenance, confidence = KIND_PROVENANCE[kind]
        target_claim = prior_claim_id or claim_id
        if family in {
            "delivered_not_displayed",
            "briefly_displayed",
            "meaningfully_displayed",
            "explicitly_read",
            "already_knew",
            "learned_now",
            "baseline_before_follow",
        }:
            target_claim = claim_id
        evidence.append(
            {
                "evidence_id": f"{prefix}-e-{index:03d}-{offset}",
                "kind": kind,
                "provenance": provenance,
                "confidence": confidence,
                "source_id": f"{prefix}-src-{index:03d}-{kind}",
                "created_at": BASE_TS + index * 10 + offset,
                "claim_id": target_claim,
                "event_id": event_id,
                "delta_id": f"{prefix}-d-{index:03d}",
            }
        )
    rationale = policy.rationale
    if ambiguous:
        rationale = (
            "Viewport metrics and prior-read context were withheld from the annotator. "
            "Do not force a knownness label."
        )
    return {
        "case_id": case_id,
        "bundle_id": _bundle(split, family),
        "split": split,
        "family": family,
        "evidence_type": policy.evidence_type,
        "source_family": source_family,
        "user_id": user_id,
        "evidence": evidence,
        "display_attempt": policy.display,
        "candidate": {
            "item_id": item_id,
            "claim_id": claim_id,
            "knowledge_id": knowledge_id,
            "event_id": event_id,
            "title": variant["title"],
            "summary": _candidate_summary(family, variant),
            "source_family": source_family,
            "publisher": publisher,
            "relation_to_prior": policy.relation,
            "importance_level": "critical" if family == "correction" else "high",
            "prior_claim_id": prior_claim_id,
            "prior_knowledge_id": prior_knowledge_id,
        },
        "knownness": policy.knownness,
        "should_surface": policy.should_surface,
        "is_novel_fact": policy.is_novel_fact,
        "is_correction": policy.is_correction,
        "rationale": rationale,
        "provenance": PROVENANCE,
        "label_protocol_version": LABEL_PROTOCOL_VERSION,
        "dataset_version": DATASET_VERSION,
        "ambiguous": ambiguous,
    }


def _cases_for_split(split: str) -> list[dict[str, Any]]:
    variants = PILOT_VARIANTS if split == "pilot" else BLIND_VARIANTS
    cases: list[dict[str, Any]] = []
    index = 1
    for family in FAMILIES:
        for variant in variants:
            cases.append(_build_case(split=split, family=family, index=index, variant=variant))
            index += 1
    extra_family = "briefly_displayed"
    extra_variant = variants[0]
    cases.append(
        _build_case(
            split=split,
            family=extra_family,
            index=index,
            variant=extra_variant,
            ambiguous=True,
        )
    )
    return cases


def _annotation(
    *,
    annotation_id: str,
    item_id: str,
    annotator_id: str,
    split: str,
    case: dict[str, Any],
    knownness: str | None,
    should_surface: bool | None,
    ambiguous: str,
    knownness_rationale: str,
    surface_rationale: str,
    novelty: str | None,
) -> dict[str, Any]:
    judgments: list[dict[str, Any]] = [
        {
            "family": "knownness",
            "value": knownness,
            "ambiguous": ambiguous,
            "rationale": knownness_rationale,
        },
        {
            "family": "should_surface",
            "value": should_surface,
            "ambiguous": ambiguous if should_surface is None else "none",
            "rationale": surface_rationale,
        },
    ]
    if novelty is not None:
        judgments.append(
            {
                "family": "novelty_revision",
                "value": novelty,
                "ambiguous": "none",
                "rationale": f"Revision class for {case['family']}.",
            }
        )
    return {
        "annotation_id": annotation_id,
        "item_id": item_id,
        "annotator_id": annotator_id,
        "protocol_version": PROTOCOL_VERSION,
        "dataset_version": DATASET_VERSION,
        "split": split,
        "provenance": PROVENANCE,
        "labeled_at": LABELED_AT,
        "notes": case["rationale"],
        "judgments": judgments,
    }


def _novelty_for(family: str) -> str:
    if family == "correction":
        return "CORRECTION"
    if family == "added_detail":
        return "DETAIL"
    if family in {
        "meaningfully_displayed",
        "explicitly_read",
        "already_knew",
        "learned_now",
        "cross_source_restatement",
        "baseline_before_follow",
    }:
        return "NON_NOVEL"
    return "NEW_FACT"


def _canonical_annotations(cases: list[dict[str, Any]], split: str) -> list[dict[str, Any]]:
    prefix = _prefix(split)
    rows: list[dict[str, Any]] = []
    for case in cases:
        ambiguous = "insufficient_context" if case["ambiguous"] else "none"
        rows.append(
            _annotation(
                annotation_id=f"{prefix}-ann-{case['case_id'][-3:]}",
                item_id=case["candidate"]["item_id"],
                annotator_id="annotator-canonical",
                split=split,
                case=case,
                knownness=None if case["ambiguous"] else case["knownness"],
                should_surface=None if case["ambiguous"] else case["should_surface"],
                ambiguous=ambiguous,
                knownness_rationale=case["rationale"],
                surface_rationale=case["rationale"],
                novelty=None if case["ambiguous"] else _novelty_for(case["family"]),
            )
        )
    return rows


def _double_label_extras(
    pilot_cases: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    by_family = {case["family"]: case for case in pilot_cases if not case["ambiguous"]}
    agree = by_family["never_seen"]
    disagree = by_family["meaningfully_displayed"]
    ambiguous = next(case for case in pilot_cases if case["ambiguous"])
    correction = by_family["correction"]

    extras = [
        _annotation(
            annotation_id="kngp-ann-agree-a",
            item_id=agree["candidate"]["item_id"],
            annotator_id="annotator-a",
            split="pilot",
            case=agree,
            knownness="new",
            should_surface=True,
            ambiguous="none",
            knownness_rationale="No prior evidence; the advisory is unseen.",
            surface_rationale="Unseen high-severity item must appear.",
            novelty="NEW_FACT",
        ),
        _annotation(
            annotation_id="kngp-ann-agree-b",
            item_id=agree["candidate"]["item_id"],
            annotator_id="annotator-b",
            split="pilot",
            case=agree,
            knownness="new",
            should_surface=True,
            ambiguous="none",
            knownness_rationale="User has never seen this Actions incident.",
            surface_rationale="Must occupy the feed this session.",
            novelty="NEW_FACT",
        ),
        _annotation(
            annotation_id="kngp-ann-disagree-a",
            item_id=disagree["candidate"]["item_id"],
            annotator_id="annotator-a",
            split="pilot",
            case=disagree,
            knownness="already_knew",
            should_surface=False,
            ambiguous="none",
            knownness_rationale="Meaningful dwell counts as already_knew.",
            surface_rationale="Same-fact reshown should stay hidden.",
            novelty="NON_NOVEL",
        ),
        _annotation(
            annotation_id="kngp-ann-disagree-b",
            item_id=disagree["candidate"]["item_id"],
            annotator_id="annotator-b",
            split="pilot",
            case=disagree,
            knownness="new",
            should_surface=True,
            ambiguous="none",
            knownness_rationale="Display without an explicit read still feels unknown.",
            surface_rationale="Would show it again in case the user skimmed.",
            novelty="NON_NOVEL",
        ),
        _annotation(
            annotation_id="kngp-ann-amb-a",
            item_id=ambiguous["candidate"]["item_id"],
            annotator_id="annotator-a",
            split="pilot",
            case=ambiguous,
            knownness=None,
            should_surface=None,
            ambiguous="insufficient_context",
            knownness_rationale="Dwell and visible ratio were not shown.",
            surface_rationale="Cannot decide surface without the viewport packet.",
            novelty=None,
        ),
        _annotation(
            annotation_id="kngp-ann-amb-b",
            item_id=ambiguous["candidate"]["item_id"],
            annotator_id="annotator-b",
            split="pilot",
            case=ambiguous,
            knownness="new",
            should_surface=True,
            ambiguous="ambiguous",
            knownness_rationale="Tentative new; the flash might have been meaningful.",
            surface_rationale="Tentative surface until metrics arrive.",
            novelty=None,
        ),
        _annotation(
            annotation_id="kngp-ann-corr-a",
            item_id=correction["candidate"]["item_id"],
            annotator_id="annotator-a",
            split="pilot",
            case=correction,
            knownness="already_knew",
            should_surface=True,
            ambiguous="none",
            knownness_rationale="User knew the prior (wrong) fact.",
            surface_rationale="Corrections must surface even when the parent fact is known.",
            novelty="CORRECTION",
        ),
        _annotation(
            annotation_id="kngp-ann-corr-b",
            item_id=correction["candidate"]["item_id"],
            annotator_id="annotator-b",
            split="pilot",
            case=correction,
            knownness="new",
            should_surface=True,
            ambiguous="none",
            knownness_rationale="The corrected fact itself is new information.",
            surface_rationale="Must surface; impact widened.",
            novelty="CORRECTION",
        ),
    ]
    pairs = [
        {
            "pair_id": "kngp-pair-agree-001",
            "item_id": agree["candidate"]["item_id"],
            "annotation_a_id": "kngp-ann-agree-a",
            "annotation_b_id": "kngp-ann-agree-b",
            "annotator_a_id": "annotator-a",
            "annotator_b_id": "annotator-b",
            "families": ["knownness", "should_surface"],
            "protocol_version": PROTOCOL_VERSION,
            "dataset_version": DATASET_VERSION,
            "split": "pilot",
        },
        {
            "pair_id": "kngp-pair-disagree-001",
            "item_id": disagree["candidate"]["item_id"],
            "annotation_a_id": "kngp-ann-disagree-a",
            "annotation_b_id": "kngp-ann-disagree-b",
            "annotator_a_id": "annotator-a",
            "annotator_b_id": "annotator-b",
            "families": ["knownness", "should_surface"],
            "protocol_version": PROTOCOL_VERSION,
            "dataset_version": DATASET_VERSION,
            "split": "pilot",
        },
        {
            "pair_id": "kngp-pair-ambiguous-001",
            "item_id": ambiguous["candidate"]["item_id"],
            "annotation_a_id": "kngp-ann-amb-a",
            "annotation_b_id": "kngp-ann-amb-b",
            "annotator_a_id": "annotator-a",
            "annotator_b_id": "annotator-b",
            "families": ["knownness", "should_surface"],
            "protocol_version": PROTOCOL_VERSION,
            "dataset_version": DATASET_VERSION,
            "split": "pilot",
        },
        {
            "pair_id": "kngp-pair-correction-001",
            "item_id": correction["candidate"]["item_id"],
            "annotation_a_id": "kngp-ann-corr-a",
            "annotation_b_id": "kngp-ann-corr-b",
            "annotator_a_id": "annotator-a",
            "annotator_b_id": "annotator-b",
            "families": ["knownness", "should_surface", "novelty_revision"],
            "protocol_version": PROTOCOL_VERSION,
            "dataset_version": DATASET_VERSION,
            "split": "pilot",
        },
    ]
    adjudications = [
        {
            "adjudication_id": "kngp-adj-knownness-001",
            "item_id": disagree["candidate"]["item_id"],
            "family": "knownness",
            "source_annotation_ids": ["kngp-ann-disagree-a", "kngp-ann-disagree-b"],
            "source_dataset_version": DATASET_VERSION,
            "produced_dataset_version": "knownness-v0.1.1",
            "resolved_value": "already_knew",
            "resolved_ambiguous": "none",
            "adjudicator_id": "adjudicator-1",
            "rationale": (
                "Meaningful dwell and visible ratio meet viewport-exposure-v1. "
                "Protocol 8.5 treats that as already_knew; same-fact reshown stays hidden."
            ),
            "protocol_version": PROTOCOL_VERSION,
            "adjudicated_at": "2026-08-29T15:00:00Z",
            "provenance": PROVENANCE,
            "split": "pilot",
        }
    ]
    return extras, pairs, adjudications


def _index(cases: list[dict[str, Any]], annotations: list[dict[str, Any]], split: str) -> dict[str, Any]:
    return {
        "split": split,
        "dataset_version": DATASET_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "bundle_ids": sorted({case["bundle_id"] for case in cases}),
        "case_ids": [case["case_id"] for case in cases],
        "user_ids": [case["user_id"] for case in cases],
        "item_ids": [case["candidate"]["item_id"] for case in cases],
        "event_ids": [case["candidate"]["event_id"] for case in cases],
        "annotation_ids": [row["annotation_id"] for row in annotations],
    }


def _dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    pilot_cases = _cases_for_split("pilot")
    blind_cases = _cases_for_split("blind")
    pilot_annotations = _canonical_annotations(pilot_cases, "pilot")
    extras, pairs, adjudications = _double_label_extras(pilot_cases)
    pilot_annotations.extend(extras)
    blind_annotations = _canonical_annotations(blind_cases, "blind")

    all_cases = [*pilot_cases, *blind_cases]
    manifest = {
        "dataset_id": "bulletfeed-knownness-gold-v0.1",
        "dataset_version": DATASET_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "split": "mixed",
        "provenance": PROVENANCE,
        "source_kind": "synthetic_fixed",
        "created_at": "2026-08-29T00:00:00Z",
        "description": (
            "Known-07 user-knownness Gold. Pilot/blind are leakage-partitioned. "
            "Do not rewrite existing Gold labels; bump dataset_version or add an overlay."
        ),
        "parent_dataset_version": None,
        "annotation_ids": [row["annotation_id"] for row in [*pilot_annotations, *blind_annotations]],
        "double_label_ids": [row["pair_id"] for row in pairs],
        "adjudication_ids": [row["adjudication_id"] for row in adjudications],
        "entry_ids": [case["case_id"] for case in all_cases],
    }
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://bulletfeed.dev/schemas/knownness-gold-label-v01.json",
        "title": "BulletFeed knownness Gold label v0.1",
        "label_protocol_version": LABEL_PROTOCOL_VERSION,
        "dataset_version": DATASET_VERSION,
        "$defs": {
            "case": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "case_id",
                    "bundle_id",
                    "split",
                    "family",
                    "evidence_type",
                    "source_family",
                    "user_id",
                    "evidence",
                    "candidate",
                    "knownness",
                    "should_surface",
                    "is_novel_fact",
                    "is_correction",
                    "rationale",
                    "provenance",
                    "label_protocol_version",
                    "dataset_version",
                ],
                "properties": {
                    "case_id": {"type": "string", "minLength": 1},
                    "bundle_id": {"type": "string", "minLength": 1},
                    "split": {"type": "string", "enum": ["pilot", "blind"]},
                    "family": {"type": "string", "enum": list(FAMILIES)},
                    "evidence_type": {
                        "type": "string",
                        "enum": [
                            "none",
                            "delivered",
                            "displayed",
                            "read",
                            "already_knew",
                            "learned_now",
                            "baseline",
                        ],
                    },
                    "source_family": {
                        "type": "string",
                        "enum": [
                            "github_release",
                            "github_advisory",
                            "osv",
                            "statuspage",
                            "rss_atom",
                            "json_feed",
                        ],
                    },
                    "user_id": {"type": "string", "minLength": 1},
                    "evidence": {"type": "array"},
                    "display_attempt": {"type": ["object", "null"]},
                    "candidate": {"type": "object"},
                    "knownness": {"type": "string", "enum": ["already_knew", "new"]},
                    "should_surface": {"type": "boolean"},
                    "is_novel_fact": {"type": "boolean"},
                    "is_correction": {"type": "boolean"},
                    "rationale": {"type": "string", "minLength": 1},
                    "provenance": {"type": "string", "minLength": 1},
                    "label_protocol_version": {"type": "string", "minLength": 1},
                    "dataset_version": {"type": "string", "minLength": 1},
                    "ambiguous": {"type": "boolean"},
                },
            }
        },
    }

    _dump(ROOT / "pilot" / "cases.json", pilot_cases)
    _dump(ROOT / "pilot" / "annotations.json", pilot_annotations)
    _dump(ROOT / "pilot" / "double_labels.json", pairs)
    _dump(ROOT / "pilot" / "adjudications.json", adjudications)
    _dump(ROOT / "pilot" / "index.json", _index(pilot_cases, pilot_annotations, "pilot"))
    _dump(ROOT / "blind" / "cases.json", blind_cases)
    _dump(ROOT / "blind" / "annotations.json", blind_annotations)
    _dump(ROOT / "blind" / "index.json", _index(blind_cases, blind_annotations, "blind"))
    _dump(ROOT / "gold_manifest_v01.json", manifest)
    _dump(ROOT / "label_schema.json", schema)
    print(f"wrote {len(pilot_cases)} pilot and {len(blind_cases)} blind knownness Gold cases")


if __name__ == "__main__":
    main()
