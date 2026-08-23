import json
from pathlib import Path

from app.evaluation.claim_sequence import evaluate_claim_sequence
from app.evaluation.release_gate import require_release_gate
from app.services.github_release_pipeline import ingest_github_release_events
from app.services.osv_pipeline import ingest_osv_events
from app.services.rss_pipeline import ingest_feed_events


def test_multisource_gold_pilot_passes_common_release_gate(database):
    path = Path(__file__).parent / "gold" / "multisource_pilot_001.json"
    bundle = json.loads(path.read_text(encoding="utf-8"))

    claim_ids: list[str] = []
    expected_revisions: list[str] = []
    expected_event_labels: list[str] = []

    for case in bundle["cases"]:
        source = case["source"]
        if source == "github_release":
            result = ingest_github_release_events(
                database,
                owner=case["owner"],
                repository=case["repository"],
                releases=[case["payload"]],
                retrieved_at=case["retrieved_at"],
            )
        elif source == "osv":
            result = ingest_osv_events(
                database,
                ecosystem=case["ecosystem"],
                package=case["package"],
                version=case["version"],
                vulnerabilities=[case["payload"]],
                retrieved_at=case["retrieved_at"],
            )
        elif source == "rss_atom":
            result = ingest_feed_events(
                database,
                preview=case["feed"],
                retrieved_at=case["retrieved_at"],
            )
        else:
            raise AssertionError(f"unsupported Gold source: {source}")

        assert len(result.claim_ids) == 1
        claim_ids.append(result.claim_ids[0])
        expected_revisions.append(case["expected_revision"])
        expected_event_labels.append(case["event_label"])

    report = evaluate_claim_sequence(
        database,
        bundle_id=bundle["bundle_id"],
        claim_ids=tuple(claim_ids),
        expected_revisions=tuple(expected_revisions),
        expected_event_labels=tuple(expected_event_labels),
    )

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
