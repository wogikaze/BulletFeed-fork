import json
from pathlib import Path

import pytest

from app.evaluation.claim_sequence import evaluate_claim_sequence
from app.evaluation.release_gate import require_release_gate
from app.services.ledger_projection import LedgerProjector
from app.services.source_ingestion import NormalizedObservation, SourceIngestionPipeline
from app.stores.claim_ledger_store import ClaimLedgerStore

_GOLD_DIR = Path(__file__).parent / "gold"
_BLIND_DATASET = json.loads((_GOLD_DIR / "blind_claim_sequences_v01.json").read_text(encoding="utf-8"))
_MANIFEST = json.loads((_GOLD_DIR / "gold_manifest_v01.json").read_text(encoding="utf-8"))
_REQUIRED_CATEGORIES = {
    "release_version",
    "incident_lifecycle",
    "security_cve",
    "policy_deprecation",
    "migration",
    "correction_conflict",
}


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


def _manifest_observation_count(entry: dict) -> int:
    path = _GOLD_DIR / entry["file"]
    data = json.loads(path.read_text(encoding="utf-8"))
    if entry["file"] == "blind_claim_sequences_v01.json":
        bundle = next(item for item in data["bundles"] if item["bundle_id"] == entry["bundle_id"])
        return len(bundle["cases"])
    summary = data.get("summary")
    if isinstance(summary, dict) and isinstance(summary.get("incidents"), list):
        return sum(len(incident["incident_updates"]) for incident in summary["incidents"])
    assert data["bundle_id"] == entry["bundle_id"]
    return len(data["cases"])


def test_gold_v01_manifest_fixes_three_pilot_twelve_blind_and_about_ninety_observations() -> None:
    entries = _MANIFEST["entries"]
    pilot = [entry for entry in entries if entry["split"] == "pilot"]
    blind = [entry for entry in entries if entry["split"] == "blind"]

    assert len(entries) == 15
    assert len(pilot) == 3
    assert len(blind) == 12
    assert len({entry["bundle_id"] for entry in entries}) == 15
    assert _REQUIRED_CATEGORIES <= {entry["category"] for entry in entries}
    observation_count = sum(entry["observations"] for entry in entries)
    assert observation_count == 87
    assert abs(observation_count - _MANIFEST["target_observations_approx"]) <= 5
    for entry in entries:
        assert (_GOLD_DIR / entry["file"]).is_file()
        assert _manifest_observation_count(entry) == entry["observations"]

    blind_ids = {bundle["bundle_id"] for bundle in _BLIND_DATASET["bundles"]}
    manifest_blind_ids = {
        entry["bundle_id"]
        for entry in blind
        if entry["file"] == "blind_claim_sequences_v01.json"
    }
    assert len(blind_ids) == 8
    assert blind_ids == manifest_blind_ids


@pytest.mark.parametrize(
    "bundle",
    _BLIND_DATASET["bundles"],
    ids=[bundle["bundle_id"] for bundle in _BLIND_DATASET["bundles"]],
)
def test_blind_claim_sequence_bundle_passes_release_gate(database, bundle: dict) -> None:
    assert bundle["category"] in _REQUIRED_CATEGORIES
    assert len(bundle["cases"]) == 6
    assert any("hard-negative" in case["event_label"] for case in bundle["cases"])
    assert any(case["expected_revision"] == "NON_NOVEL" for case in bundle["cases"])

    ingestion = SourceIngestionPipeline(database)
    ledger = ClaimLedgerStore(database)
    claim_ids: list[str] = []
    expected_revisions: list[str] = []
    expected_event_labels: list[str] = []
    event_ids: set[str] = set()

    for case in bundle["cases"]:
        source_type = case.get("source_type", bundle.get("source_type"))
        source_key = case.get("source_key", bundle.get("source_key"))
        assert source_type is not None
        assert source_key is not None
        observation = ingestion.ingest_many(
            (
                NormalizedObservation(
                    source_type=source_type,
                    source_key=source_key,
                    source_observation_id=case["id"],
                    payload={
                        "id": case["id"],
                        "value": case["value"],
                        "detail": case["detail"],
                    },
                    original_url=f"https://gold.bulletfeed.test/{bundle['bundle_id']}/{case['id']}",
                    published_at=case["valid_at"],
                ),
            ),
            retrieved_at=case.get("retrieved_at", case["valid_at"]),
        )[0]
        claim = ledger.ingest(
            observation,
            source_event_id=case.get("source_event_id", case["event_label"]),
            canonical_event_key=case.get("canonical_event_key"),
            title=bundle["title"],
            slot=case.get("slot", bundle["slot"]),
            value=case["value"],
            detail=case["detail"],
            valid_at=case["valid_at"],
            source_updated_at=case.get("source_updated_at", case["valid_at"]),
            evidence_text=case["detail"],
            explicit_correction=case.get("explicit_correction", False),
            unresolved_source_conflict=case.get("unresolved_source_conflict", False),
        )
        claim_ids.append(claim.claim_id)
        expected_revisions.append(case["expected_revision"])
        expected_event_labels.append(case["event_label"])
        event_ids.add(claim.event_id)

    projector = LedgerProjector(database)
    for event_id in event_ids:
        projector.project_event(event_id)

    report = evaluate_claim_sequence(
        database,
        bundle_id=bundle["bundle_id"],
        claim_ids=tuple(claim_ids),
        expected_revisions=tuple(expected_revisions),
        expected_event_labels=tuple(expected_event_labels),
    )
    _assert_perfect_gate(report)
