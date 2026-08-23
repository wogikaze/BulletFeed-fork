from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.database import Database
from app.services.ledger_projection import LedgerProjector
from app.services.statuspage_pipeline import StatuspagePipeline


@dataclass(frozen=True)
class GoldEvaluationReport:
    bundle_id: str
    revision_accuracy: float
    delta_precision: float
    delta_recall: float
    repetition_rate: float
    correction_recall: float
    evidence_coverage: float
    unsupported_claim_count: int
    false_merge_count: int
    false_split_count: int


def evaluate_statuspage_bundle(
    database: Database,
    bundle: dict[str, Any],
) -> GoldEvaluationReport:
    bundle_id = str(bundle["bundle_id"])
    page_id = str(bundle["page_id"])
    summary = bundle["summary"]
    gold = bundle["gold"]
    expected_revision: dict[str, str] = dict(gold["revision_by_update"])
    expected_event: dict[str, str] = dict(gold["event_by_update"])

    result = StatuspagePipeline(database).ingest_summary(
        page_id=page_id,
        summary=summary,
        retrieved_at=str(bundle["retrieved_at"]),
    )
    projector = LedgerProjector(database)
    for event_id in result.event_ids:
        projector.project_event(event_id)

    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT o.source_observation_id AS update_id,
                   c.id AS claim_id,
                   c.event_id,
                   r.relation_type
            FROM state_claims c
            JOIN observations o ON o.id = c.observation_id
            JOIN claim_relations r ON r.new_claim_id = c.id
            WHERE o.source_type = 'statuspage' AND o.source_key = ?
            """,
            (page_id,),
        ).fetchall()
        delta_claim_ids = {
            row["claim_id"]
            for row in connection.execute(
                """
                SELECT m.claim_id
                FROM delta_claim_map m
                JOIN deltas d ON d.id = m.delta_id
                WHERE d.active = 1
                """
            ).fetchall()
        }
        evidence_claim_ids = {
            row["claim_id"]
            for row in connection.execute(
                "SELECT DISTINCT claim_id FROM claim_evidence"
            ).fetchall()
        }

    actual = {
        row["update_id"]: {
            "claim_id": row["claim_id"],
            "event_id": row["event_id"],
            "revision": row["relation_type"],
        }
        for row in rows
        if row["update_id"] in expected_revision
    }

    revision_hits = sum(
        1
        for update_id, expected in expected_revision.items()
        if actual.get(update_id, {}).get("revision") == expected
    )
    revision_accuracy = _ratio(revision_hits, len(expected_revision))

    gold_novel = {
        update_id
        for update_id, revision in expected_revision.items()
        if revision != "NON_NOVEL"
    }
    gold_non_novel = set(expected_revision) - gold_novel
    actual_delta = {
        update_id
        for update_id, value in actual.items()
        if value["claim_id"] in delta_claim_ids
    }
    delta_precision = _ratio(len(actual_delta & gold_novel), len(actual_delta))
    delta_recall = _ratio(len(actual_delta & gold_novel), len(gold_novel))
    repetition_rate = _ratio(len(actual_delta & gold_non_novel), len(actual_delta), empty=0.0)

    gold_corrections = {
        update_id
        for update_id, revision in expected_revision.items()
        if revision == "CORRECTION"
    }
    surfaced_corrections = {
        update_id
        for update_id in gold_corrections
        if update_id in actual_delta and actual.get(update_id, {}).get("revision") == "CORRECTION"
    }
    correction_recall = _ratio(len(surfaced_corrections), len(gold_corrections))

    displayed_claim_ids = {
        actual[update_id]["claim_id"]
        for update_id in actual_delta
    }
    supported_claim_ids = displayed_claim_ids & evidence_claim_ids
    evidence_coverage = _ratio(len(supported_claim_ids), len(displayed_claim_ids))
    unsupported_claim_count = len(displayed_claim_ids - evidence_claim_ids)

    false_merge_count, false_split_count = _event_identity_errors(actual, expected_event)

    return GoldEvaluationReport(
        bundle_id=bundle_id,
        revision_accuracy=revision_accuracy,
        delta_precision=delta_precision,
        delta_recall=delta_recall,
        repetition_rate=repetition_rate,
        correction_recall=correction_recall,
        evidence_coverage=evidence_coverage,
        unsupported_claim_count=unsupported_claim_count,
        false_merge_count=false_merge_count,
        false_split_count=false_split_count,
    )


def _event_identity_errors(
    actual: dict[str, dict[str, str]],
    expected_event: dict[str, str],
) -> tuple[int, int]:
    update_ids = list(expected_event)
    false_merges = 0
    false_splits = 0
    for index, left in enumerate(update_ids):
        for right in update_ids[index + 1 :]:
            left_actual = actual.get(left, {}).get("event_id")
            right_actual = actual.get(right, {}).get("event_id")
            if left_actual is None or right_actual is None:
                continue
            same_gold = expected_event[left] == expected_event[right]
            same_actual = left_actual == right_actual
            if not same_gold and same_actual:
                false_merges += 1
            elif same_gold and not same_actual:
                false_splits += 1
    return false_merges, false_splits


def _ratio(numerator: int, denominator: int, *, empty: float = 1.0) -> float:
    if denominator == 0:
        return empty
    return numerator / denominator
