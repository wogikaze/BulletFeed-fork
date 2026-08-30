from pathlib import Path

from app.database import Database
from app.evaluation.m1_zero_to_useful import (
    PERSONA_MANIFEST_VERSION,
    built_in_personas,
    load_persona_manifest,
    run_qualification,
    write_persona_manifest,
)

_MANIFEST = Path(__file__).parent / "gold" / "m1_personas" / "v01" / "personas.json"


def test_persona_manifest_meets_m1_floor(tmp_path: Path) -> None:
    write_persona_manifest(_MANIFEST)
    personas = load_persona_manifest(_MANIFEST)
    assert len(personas) == 30
    assert {row.cohort for row in personas} == {"cold_start", "history_rich"}
    assert {"ja", "en", "mixed"} <= {row.language for row in personas}
    assert {"broad", "narrow"} <= {row.breadth for row in personas}
    assert {"high", "low"} <= {row.security for row in personas}
    assert any(row.expect_empty_reason == "no_topics_abstention" for row in personas)


def test_qualification_attempts_all_constructed_personas(tmp_path: Path) -> None:
    index = {"n": 0}

    def factory() -> Database:
        index["n"] += 1
        database = Database(tmp_path / f"m1-{index['n']}.db")
        database.initialize()
        return database

    report = run_qualification(factory, built_in_personas())
    assert report["persona_manifest_version"] == PERSONA_MANIFEST_VERSION
    assert report["label_source"] == "constructed"
    assert report["attempted"] == 30
    assert report["persona_count"] == 30
    assert report["tenant_leak"] == 0
    assert report["harness_version"] == "m1-zero-to-useful-v02"
    assert all(
        {"discovery", "activation"} <= {stage["stage"] for stage in row["stages"]}
        for row in report["reports"]
    )
    intended = [
        row
        for row in report["reports"]
        if row["intended_empty_feed"]
    ]
    assert intended
    assert all(row["unexpected_empty_feed"] is False for row in intended)
