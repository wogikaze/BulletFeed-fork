import json
from pathlib import Path

from app.services.relation import RELATION_FEATURE_VERSION

REPORT = (
    Path(__file__).resolve().parent
    / "gold"
    / "m6"
    / "v01"
    / "cluster_recall_after_identity.json"
)
FAMILIES = {
    "package_release_manager",
    "rust_compiler_contributor",
    "javascript_tooling_maintainer",
}


def test_cluster_recall_after_identity_is_full_cluster_and_not_blind() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    assert payload["report_version"] == "m6-cluster-recall-after-identity-v1"
    assert payload["label_source"] == "AI-silver"
    assert payload["human_gold"] is False
    assert payload["blind_read"] is False
    assert payload["blind_records_loaded"] is False
    assert payload["relation_feature_version"] == RELATION_FEATURE_VERSION
    assert set(payload["persona_families"]) == FAMILIES
    for _family, row in payload["persona_families"].items():
        assert row["before"]["sample_count"] == row["after"]["sample_count"]
        assert row["before"]["judgment_count"] == row["after"]["judgment_count"]
        assert "important_unknown_recall_at_10" in row["before"]
        assert "important_unknown_recall_at_10" in row["after"]
        assert "iu_recall_at_10_delta" in row
    assert payload["headline_at_10"]["after"]["important_unknown_recall_at_10"] is not None
