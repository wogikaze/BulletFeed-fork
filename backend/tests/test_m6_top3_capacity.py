import json
from pathlib import Path

from app.services.multiobjective_ranker import RANKING_POLICY_VERSION

REPORT = (
    Path(__file__).resolve().parent
    / "gold"
    / "m6"
    / "v01"
    / "top3_capacity_diagnosis.json"
)


def test_top3_capacity_diagnosis_explains_unmoving_family_iu() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    assert payload["report_version"] == "m6-top3-capacity-diagnosis-v1"
    assert payload["human_gold"] is False
    assert payload["blind_read"] is False
    assert payload["ranking_policy_version"] == RANKING_POLICY_VERSION
    families = payload["persona_families"]
    package = families["package_release_manager"]
    rust = families["rust_compiler_contributor"]
    javascript = families["javascript_tooling_maintainer"]
    assert package["k10_saturated_profiles"] == 4
    assert package["vacuous_perfect_recall_profiles"] == 0
    assert package["mean_important_unknown_recall_at_10"] == 0.036824
    assert rust["k10_saturated_profiles"] == 4
    assert rust["mean_important_unknown_recall_at_10"] == 0.535971
    assert javascript["k10_saturated_profiles"] == 2
    assert javascript["vacuous_perfect_recall_profiles"] == 2
    assert javascript["mean_important_unknown_recall_at_10"] == 0.522727
    assert all(row["k10_saturated"] for row in package["profiles"])
    js_rows = {row["user_id"]: row for row in javascript["profiles"]}
    assert js_rows["prf_m2_d_javascript_tooling_maintainer_02"]["vacuous_perfect_recall"] is True
    assert js_rows["prf_m2_d_javascript_tooling_maintainer_03"]["vacuous_perfect_recall"] is True
    assert "Do not run #171" in " ".join(payload["notes"])
