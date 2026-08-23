import json
from pathlib import Path

from app.evaluation.claim_sequence import evaluate_claim_sequence
from app.evaluation.release_gate import require_release_gate
from app.services.github_advisory_pipeline import ingest_github_advisory_events
from app.services.json_feed_pipeline import ingest_json_feed_events

_GOLD_DIR = Path(__file__).parent / "gold"


def _evaluate(database, *, bundle: dict, ingest_case):
    claim_ids: list[str] = []
    revisions: list[str] = []
    event_labels: list[str] = []
    for case in bundle["cases"]:
        result = ingest_case(case)
        assert len(result.claim_ids) == 1
        claim_ids.append(result.claim_ids[0])
        revisions.append(case["expected_revision"])
        event_labels.append(case["event_label"])
    return evaluate_claim_sequence(
        database,
        bundle_id=bundle["bundle_id"],
        claim_ids=tuple(claim_ids),
        expected_revisions=tuple(revisions),
        expected_event_labels=tuple(event_labels),
    )


def _assert_perfect_gate(report) -> None:
    assert report.revision_accuracy == 1.0
    assert report.delta_precision == 1.0
    assert report.delta_recall == 1.0
    assert report.repetition_rate == 0.0
    assert report.correction_recall == 1.0
    assert report.evidence_coverage == 1.0
    assert report.unsupported_claim_count == 0
    assert report.false_merge_count == 0
    assert report.false_split_count == 0
    require_release_gate(report)


def test_github_advisory_gold_covers_detail_withdrawal_and_hard_negative(database):
    bundle = json.loads((_GOLD_DIR / "github_advisory_pilot_001.json").read_text(encoding="utf-8"))

    report = _evaluate(
        database,
        bundle=bundle,
        ingest_case=lambda case: ingest_github_advisory_events(
            database,
            advisories=[case["payload"]],
            retrieved_at=case["retrieved_at"],
            ecosystem=bundle["ecosystem"],
        ),
    )

    _assert_perfect_gate(report)


def test_json_feed_gold_covers_revision_and_same_publisher_hard_negative(database):
    bundle = json.loads((_GOLD_DIR / "json_feed_pilot_001.json").read_text(encoding="utf-8"))

    report = _evaluate(
        database,
        bundle=bundle,
        ingest_case=lambda case: ingest_json_feed_events(
            database,
            feed=case["feed"],
            feed_url=bundle["feed_url"],
            retrieved_at=case["retrieved_at"],
        ),
    )

    _assert_perfect_gate(report)
