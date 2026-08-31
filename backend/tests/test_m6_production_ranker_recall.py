import json
from pathlib import Path

from app.services.multiobjective_ranker import RANKING_POLICY_VERSION

REPORT = (
    Path(__file__).resolve().parent
    / "gold"
    / "m6"
    / "v01"
    / "cluster_recall_after_production_ranker.json"
)
FAMILIES = {
    "package_release_manager",
    "rust_compiler_contributor",
    "javascript_tooling_maintainer",
}


def test_production_ranker_remeasure_is_full_cluster_and_not_blind() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    assert payload["report_version"] == "m6-cluster-recall-after-production-ranker-v1"
    assert payload["label_source"] == "AI-silver"
    assert payload["human_gold"] is False
    assert payload["blind_read"] is False
    assert payload["blind_records_loaded"] is False
    assert payload["ranking_policy_version"] == RANKING_POLICY_VERSION
    assert (
        payload["production_ranking_contract"]
        == "app.services.multiobjective_ranker.rank_personalization_corpus"
    )
    assert set(payload["persona_families"]) == FAMILIES
    for row in payload["persona_families"].values():
        assert row["before"]["sample_count"] == row["after"]["sample_count"]
        assert row["before"]["judgment_count"] == row["after"]["judgment_count"]
        assert "important_unknown_recall_at_10" in row["before"]
        assert "important_unknown_recall_at_10" in row["after"]
        assert "iu_recall_at_10_delta" in row
        assert row["after"]["unknown_but_hidden_rate"] <= row["before"]["unknown_but_hidden_rate"]
        assert row["iu_recall_at_10_delta"] == 0.0
    after_v5 = payload["headline_at_10"]["after_feed_order_v5"][
        "important_unknown_recall_at_10"
    ]
    after_ranker = payload["headline_at_10"]["after_production_ranker"][
        "important_unknown_recall_at_10"
    ]
    assert after_ranker < after_v5
    assert payload["headline_at_10"]["after_production_ranker"][
        "important_unknown_recall_at_10"
    ] is not None
