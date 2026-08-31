from fastapi.testclient import TestClient

from app.database import Database
from app.db.seed import seed_catalog, seed_user_workspace
from app.evaluation.delta_kind_e2e import (
    DATASET_VERSION,
    evaluate_delta_kind_e2e,
    first_broken_stage,
    run_additional_detail,
    run_duplicate_paraphrase,
    run_explicit_correction,
    run_state_update,
    run_syndication,
    run_uncertain_knownness,
    run_unresolved_conflict,
)


def test_first_broken_stage_is_the_earliest_failure() -> None:
    from app.evaluation.delta_kind_e2e import StageCheck

    stages = {
        "source": StageCheck(True),
        "acquire": StageCheck(True),
        "claim": StageCheck(False, "no claim"),
        "event_delta": StageCheck(False, "later"),
        "false_merge": StageCheck(True),
    }
    assert first_broken_stage(stages) == "claim"


def test_delta_kinds_are_split_through_source_to_api(database: Database) -> None:
    report = evaluate_delta_kind_e2e(database)
    failed = [case for case in report.cases if case.first_broken_stage != "ok"]
    assert report.version == DATASET_VERSION
    assert report.false_merge_count == 0
    assert failed == [], [
        (case.scenario_id, case.first_broken_stage, case.stages[case.first_broken_stage].detail)
        for case in failed
    ]
    assert report.passed is True


def test_false_merge_is_gated_harder_than_a_split(database: Database) -> None:
    conflict = run_unresolved_conflict(database)
    uncertain = run_uncertain_knownness(database)
    assert conflict.first_broken_stage == "ok"
    assert uncertain.first_broken_stage == "ok"
    assert conflict.stages["false_merge"].ok is True
    assert uncertain.stages["false_merge"].ok is True


def test_each_required_delta_scenario_names_its_kind(database: Database) -> None:
    expected = {
        "duplicate_paraphrase": "new_fact",
        "additional_detail": "additional",
        "state_update": "state_update",
        "explicit_correction": "correction",
        "unresolved_conflict": "conflict",
        "syndication": "new_fact",
        "uncertain_knownness": "new_fact",
    }
    runners = {
        "duplicate_paraphrase": run_duplicate_paraphrase,
        "additional_detail": run_additional_detail,
        "state_update": run_state_update,
        "explicit_correction": run_explicit_correction,
        "unresolved_conflict": run_unresolved_conflict,
        "syndication": run_syndication,
        "uncertain_knownness": run_uncertain_knownness,
    }
    for scenario_id, runner in runners.items():
        result = runner(database)
        assert result.first_broken_stage == "ok", (
            scenario_id,
            result.first_broken_stage,
            result.stages.get(result.first_broken_stage),
        )
        assert result.expected_delta_kind == expected[scenario_id]


def test_feed_http_returns_versioned_display_reason(
    client: TestClient,
    auth_headers: dict[str, str],
    database: Database,
) -> None:
    with database.connect() as connection:
        user = connection.execute("SELECT id FROM users WHERE github_user_id = 123").fetchone()
        assert user is not None
        seed_catalog(connection)
        seed_user_workspace(connection, user["id"])

    response = client.get("/v1/feed", headers=auth_headers, params={"limit": 5})
    assert response.status_code == 200
    items = response.json()["items"]
    assert items
    for item in items:
        reason = item["displayReason"]
        assert reason["policyVersion"]
        assert reason["rankingPolicyVersion"]
        assert reason["primaryCode"]
        assert reason["text"]
        assert reason["codes"]
        assert reason["matchKind"] in {"direct", "adjacent", "inferred", "reference"}
        assert reason["deltaKind"] in {
            "new_fact",
            "additional",
            "state_update",
            "correction",
            "conflict",
            "duplicate",
        }
        assert reason["independentEvidenceCount"] >= 1
        assert "知っている" not in reason["text"]
        assert "知らない" not in reason["text"]
