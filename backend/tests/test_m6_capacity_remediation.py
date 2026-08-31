import json
from pathlib import Path

from app.services.multiobjective_ranker import RANKING_POLICY_VERSION
from app.services.ranking_capacity import CAPACITY_POLICY_VERSION

REPORT = (
    Path(__file__).resolve().parent
    / "gold"
    / "m6"
    / "v01"
    / "capacity_remediation_before_after.json"
)
FAMILIES = {
    "package_release_manager",
    "rust_compiler_contributor",
    "javascript_tooling_maintainer",
}


def test_capacity_before_after_is_dev_only_and_separates_policies() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    assert payload["report_version"] == "m6-capacity-remediation-v1"
    assert payload["human_gold"] is False
    assert payload["blind_read"] is False
    assert payload["blind_records_loaded"] is False
    assert payload["ranking_policy_version"] == RANKING_POLICY_VERSION
    assert payload["capacity_policy_version"] == CAPACITY_POLICY_VERSION
    assert payload["ranking_policy_version"] != payload["capacity_policy_version"]
    assert set(payload["before"]["persona_families"]) == FAMILIES
    assert set(payload["after"]["persona_families"]) == FAMILIES
    assert set(payload["policy_comparison"]) == {
        "off",
        "topic_cap",
        "reserved",
        "source_cap",
        "two_stage",
    }
    assert payload["guards"]["cards_to_first_important_unknown_not_worsened"] is True
    assert payload["guards"]["hidden_count_not_increased"] is True
    assert payload["guards"]["item_iu_recall_at_10_not_worsened"] is True
    assert payload["guards"]["unknown_but_hidden_not_worsened"] is True
    assert payload["guards"]["false_merge_unchanged"] is True
    assert payload["false_merge"]["after"] <= payload["false_merge"]["before"]
    assert payload["intended_metric_moved"] is True
    freeze = json.loads(
        (REPORT.parent / "capacity_production_freeze.json").read_text(encoding="utf-8")
    )
    assert freeze["capacity_policy_version"] == CAPACITY_POLICY_VERSION
    assert freeze["ranking_policy_version"] == RANKING_POLICY_VERSION
    assert freeze["oneshot_blind_ran"] is False
    assert freeze["weights_unchanged"] is True
    for family in FAMILIES:
        before = payload["before"]["persona_families"][family]["summary"]
        after = payload["after"]["persona_families"][family]["summary"]
        assert before["at_10"]["important_unknown_recall"] <= 1.0
        assert after["at_10"]["important_unknown_recall"] >= before["at_10"]["important_unknown_recall"]
        assert after["hidden_count"] <= before["hidden_count"]
        assert after["mean_cards_to_first_important_unknown"] <= (
            before["mean_cards_to_first_important_unknown"] + 1e-9
        )
    assert "Do not chase" in " ".join(payload["notes"])
    assert payload["blind_gate"]["run"] is False
