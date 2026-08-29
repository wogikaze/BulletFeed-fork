import json
from pathlib import Path

from app.evaluation.coreference import CandidateRetrievalSample, evaluate_candidate_retrieval
from app.evaluation.semantic_quality import confidence_buckets
from app.services.event_coreference import CoreferenceInput, EventCoreferenceEngine
from app.services.source_ingestion import NormalizedObservation, SourceIngestionPipeline
from app.stores.claim_ledger_store import ClaimLedgerStore

_GOLD = Path(__file__).parent / "gold" / "v02" / "blind" / "semantic_hard_cases.json"


def _title(event_label: str) -> str:
    return event_label.replace("-", " ")


def test_event_coreference_has_full_candidate_recall_and_zero_identity_errors_on_gold(database):
    dataset = json.loads(_GOLD.read_text(encoding="utf-8"))
    bundle = next(
        item
        for item in dataset["bundles"]
        if item["bundle_id"] == "coreference-same-entity-hard-negative-001"
    )
    ingestion = SourceIngestionPipeline(database)
    ledger = ClaimLedgerStore(database)
    engine = EventCoreferenceEngine(database, candidate_limit=20)
    expected_events: dict[str, str] = {}
    samples: list[CandidateRetrievalSample] = []
    calibration: list[tuple[str, bool, bool]] = []
    false_merges = 0
    false_splits = 0

    for index, case in enumerate(bundle["cases"]):
        incoming = CoreferenceInput(
            source_type="rss_atom" if index % 2 == 0 else "json_feed",
            source_key=f"gold-coreference-{index % 2}",
            source_event_id=case["id"],
            title=_title(case["event_label"]),
            subject=case["detail"],
            valid_at=case["valid_at"],
        )
        expected_event_id = expected_events.get(case["event_label"])
        if expected_event_id is not None:
            candidates = engine.retrieve_candidates(incoming)
            samples.append(
                CandidateRetrievalSample(
                    expected_event_id=expected_event_id,
                    candidate_event_ids=tuple(candidate.event_id for candidate in candidates.candidates),
                )
            )
            decision = engine.resolve(incoming)
            correct = decision.label == "same_event" and decision.candidate_event_id == expected_event_id
            calibration.append((decision.confidence, correct, decision.label == "uncertain"))
            if not correct:
                false_splits += 1
            continue

        decision = engine.resolve(incoming)
        correct = decision.label != "same_event"
        calibration.append((decision.confidence, correct, decision.label == "uncertain"))
        if not correct:
            false_merges += 1
        observation = ingestion.ingest_many(
            (
                NormalizedObservation(
                    source_type=incoming.source_type,
                    source_key=incoming.source_key,
                    source_observation_id=case["id"],
                    payload={"detail": case["detail"]},
                    original_url=f"https://gold.bulletfeed.test/coreference/{case['id']}",
                    published_at=case["valid_at"],
                ),
            ),
            retrieved_at=case["valid_at"],
        )[0]
        claim = ledger.ingest(
            observation,
            source_event_id=case["id"],
            title=incoming.title,
            slot="state",
            value=case["value"],
            detail=case["detail"],
            valid_at=case["valid_at"],
            evidence_text=case["detail"],
        )
        expected_events[case["event_label"]] = claim.event_id

    report = evaluate_candidate_retrieval(tuple(samples))
    assert report.samples >= 3
    assert report.candidate_recall >= 0.99
    assert report.max_candidate_set_size <= 20
    assert false_merges == 0
    assert false_splits == 0
    buckets = confidence_buckets(tuple(calibration))
    assert buckets
    for bucket in buckets:
        if bucket.confidence in {"high", "medium"}:
            assert bucket.accuracy >= 0.90
    assert "event-coreference-v2" in engine.decision_version
    assert "same=0.75" in engine.decision_version
