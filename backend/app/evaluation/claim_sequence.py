from __future__ import annotations

from app.database import Database
from app.evaluation.gold import GoldEvaluationReport


def evaluate_claim_sequence(
    database: Database,
    *,
    bundle_id: str,
    claim_ids: tuple[str, ...],
    expected_revisions: tuple[str, ...],
    expected_event_labels: tuple[str, ...],
) -> GoldEvaluationReport:
    if not (len(claim_ids) == len(expected_revisions) == len(expected_event_labels)):
        raise ValueError("claim sequence and gold labels must have the same length")
    if len(set(claim_ids)) != len(claim_ids):
        raise ValueError("claim sequence must contain unique claims")

    with database.connect() as connection:
        actual: list[dict[str, str]] = []
        for claim_id in claim_ids:
            row = connection.execute(
                """
                SELECT c.event_id, r.relation_type
                FROM state_claims c
                JOIN claim_relations r ON r.new_claim_id = c.id
                WHERE c.id = ?
                """,
                (claim_id,),
            ).fetchone()
            if row is None:
                actual.append({"event_id": "", "revision": ""})
            else:
                actual.append(
                    {
                        "event_id": row["event_id"],
                        "revision": row["relation_type"],
                    }
                )
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
            for row in connection.execute("SELECT DISTINCT claim_id FROM claim_evidence").fetchall()
        }

    revision_hits = sum(
        1
        for index, expected in enumerate(expected_revisions)
        if actual[index]["revision"] == expected
    )
    revision_accuracy = _ratio(revision_hits, len(expected_revisions))

    gold_novel = {index for index, value in enumerate(expected_revisions) if value != "NON_NOVEL"}
    gold_non_novel = set(range(len(expected_revisions))) - gold_novel
    actual_delta = {index for index, claim_id in enumerate(claim_ids) if claim_id in delta_claim_ids}
    true_positive = actual_delta & gold_novel
    delta_precision = _ratio(len(true_positive), len(actual_delta))
    delta_recall = _ratio(len(true_positive), len(gold_novel))
    repetition_rate = _ratio(len(actual_delta & gold_non_novel), len(actual_delta), empty=0.0)

    correction_indices = {
        index for index, value in enumerate(expected_revisions) if value == "CORRECTION"
    }
    surfaced_corrections = {
        index
        for index in correction_indices
        if index in actual_delta and actual[index]["revision"] == "CORRECTION"
    }
    correction_recall = _ratio(len(surfaced_corrections), len(correction_indices))

    displayed_claim_ids = {claim_ids[index] for index in actual_delta}
    supported_claim_ids = displayed_claim_ids & evidence_claim_ids
    evidence_coverage = _ratio(len(supported_claim_ids), len(displayed_claim_ids))
    unsupported_claim_count = len(displayed_claim_ids - evidence_claim_ids)
    false_merge_count, false_split_count = _identity_errors(actual, expected_event_labels)

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


def _identity_errors(
    actual: list[dict[str, str]],
    expected_event_labels: tuple[str, ...],
) -> tuple[int, int]:
    false_merges = 0
    false_splits = 0
    for left in range(len(expected_event_labels)):
        for right in range(left + 1, len(expected_event_labels)):
            left_event = actual[left]["event_id"]
            right_event = actual[right]["event_id"]
            if not left_event or not right_event:
                continue
            expected_same = expected_event_labels[left] == expected_event_labels[right]
            actual_same = left_event == right_event
            if not expected_same and actual_same:
                false_merges += 1
            elif expected_same and not actual_same:
                false_splits += 1
    return false_merges, false_splits


def _ratio(numerator: int, denominator: int, *, empty: float = 1.0) -> float:
    if denominator == 0:
        return empty
    return numerator / denominator
