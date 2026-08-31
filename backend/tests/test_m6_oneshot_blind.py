import json
from pathlib import Path

from app.evaluation.personalization_gold import scan_python_sources
from app.services.multiobjective_ranker import RANKING_POLICY_VERSION
from app.services.ranking_capacity import CAPACITY_POLICY_VERSION
from app.services.relation import RELATION_FEATURE_VERSION

BACKEND = Path(__file__).resolve().parents[1]
APP = BACKEND / "app"
REPORT = BACKEND / "tests" / "gold" / "m6" / "v01" / "oneshot_blind_aggregate.json"
FROZEN_SHA = "b1befc9ee4ab04eefe64820ca27332438f8946ce"


def _payload() -> dict:
    return json.loads(REPORT.read_text(encoding="utf-8"))


def test_oneshot_blind_report_records_frozen_sha_and_does_not_retune() -> None:
    payload = _payload()
    assert payload["report_version"] == "m6-oneshot-blind-aggregate-v1"
    assert payload["status"] == "oneshot_blind_recorded"
    assert payload["aggregate_status"] in {"available", "not_scorable"}
    assert payload["repository_sha"] == FROZEN_SHA
    assert payload["human_gold"] is False
    assert payload["label_source"] == "AI-silver"
    assert payload["blind_read"] is True
    assert payload["blind_records_loaded"] is True
    assert payload["oneshot"] is True
    assert payload["retune"] is False
    assert payload["production_code_unchanged"] is True
    assert payload["ranking_policy_version"] == RANKING_POLICY_VERSION
    assert payload["capacity_policy_version"] == CAPACITY_POLICY_VERSION
    assert payload["relation_feature_version"] == RELATION_FEATURE_VERSION
    assert (
        payload["production_ranking_contract"]
        == "app.services.multiobjective_ranker.rank_personalization_corpus"
    )
    assert payload["holdout"]["split"] == "blind"
    assert payload["holdout"]["judgments"] >= 1
    assert "headline" in payload
    assert "segments" in payload
    assert "uncertainty" in payload
    assert set(payload["top3_persona_families"]) == {
        "package_release_manager",
        "rust_compiler_contributor",
        "javascript_tooling_maintainer",
    }
    assert any("Do not retune" in note for note in payload["notes"])


def test_production_app_does_not_import_m6_blind_eval() -> None:
    tokens = {
        "m6_blind_eval",
        "run_m6_blind_aggregate",
        "load_m6_blind_holdout",
        "evaluate_m6_oneshot_blind",
        "oneshot_blind_aggregate.json",
    }
    assert scan_python_sources(APP, tokens) == ()
