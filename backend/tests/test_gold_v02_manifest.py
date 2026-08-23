import json
from pathlib import Path

_GOLD = Path(__file__).parent / "gold"
_V02 = _GOLD / "v02"
_MANIFEST = json.loads((_V02 / "gold_manifest_v02.json").read_text(encoding="utf-8"))
_PILOT = json.loads((_V02 / "pilot" / "index.json").read_text(encoding="utf-8"))
_BLIND = json.loads((_V02 / "blind" / "index.json").read_text(encoding="utf-8"))
_REAL_STATUS = json.loads(
    (_V02 / "real" / "github_status_incident_metadata.json").read_text(encoding="utf-8")
)
_REQUIRED_CATEGORIES = {
    "release_version",
    "incident_lifecycle",
    "security_cve",
    "policy_deprecation",
    "migration",
    "correction_conflict",
}


def test_gold_v02_meets_size_real_data_and_provenance_floors() -> None:
    entries = _MANIFEST["entries"]
    observation_count = sum(entry["observations"] for entry in entries)
    real_count = sum(
        entry["observations"]
        for entry in entries
        if entry["kind"] in {"real_public_source", "real_public_source_metadata"}
    )

    assert len(entries) == 47
    assert len(entries) >= _MANIFEST["minimum_bundles"]
    assert observation_count == 251
    assert observation_count >= _MANIFEST["minimum_observations"]
    assert real_count == 158
    assert real_count / observation_count >= _MANIFEST["minimum_real_observation_ratio"]
    assert len({entry["bundle_id"] for entry in entries}) == len(entries)
    assert _REQUIRED_CATEGORIES <= {entry["category"] for entry in entries}
    for entry in entries:
        assert entry["split"] in {"pilot", "blind"}
        assert entry["provenance"]
        assert isinstance(entry["hard_negative"], bool)
        assert entry["kind"] in {
            "synthetic_fixed",
            "real_public_source",
            "real_public_source_metadata",
        }


def test_real_metadata_is_fixed_public_source_data_not_generated_cases() -> None:
    incidents = _REAL_STATUS["incidents"]
    assert _REAL_STATUS["provenance"] == "https://www.githubstatus.com/api/v2/incidents.json"
    assert _REAL_STATUS["snapshot_kind"] == "real_public_source_metadata"
    assert _REAL_STATUS["observations_per_incident"] == 5
    assert len(incidents) == 28
    assert len({incident["id"] for incident in incidents}) == 28
    for incident in incidents:
        assert incident["status"] == "resolved"
        assert incident["impact"] in {"none", "minor", "major", "critical"}
        assert incident["created_at"]
        assert incident["resolved_at"]
        assert incident["updated_at"]


def test_pilot_and_blind_indexes_partition_every_manifest_bundle() -> None:
    entries = _MANIFEST["entries"]
    pilot_ids = set(_PILOT["bundle_ids"])
    blind_ids = set(_BLIND["bundle_ids"])
    manifest_ids = {entry["bundle_id"] for entry in entries}

    assert _PILOT["split"] == "pilot"
    assert _BLIND["split"] == "blind"
    assert not pilot_ids & blind_ids
    assert pilot_ids | blind_ids == manifest_ids
    assert len(pilot_ids) == 3
    assert len(blind_ids) == 44
    for entry in entries:
        expected = pilot_ids if entry["split"] == "pilot" else blind_ids
        assert entry["bundle_id"] in expected


def test_synthetic_hard_cases_are_never_counted_as_real_source_observations() -> None:
    entries = _MANIFEST["entries"]
    synthetic_ids = {
        "semantic-paraphrase-blind-001",
        "semantic-negation-version-blind-001",
        "coreference-same-entity-hard-negative-001",
    }
    indexed = {entry["bundle_id"]: entry for entry in entries}
    assert synthetic_ids <= set(indexed)
    for bundle_id in synthetic_ids:
        assert indexed[bundle_id]["kind"] == "synthetic_fixed"
        assert indexed[bundle_id]["provenance"] == "adversarial test fixture"
