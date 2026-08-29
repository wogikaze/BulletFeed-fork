from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.evaluation.real_world_validation import (
    CONTRACT_VERSION,
    DATASET_VERSION,
    REQUIRED_SOURCE_FIELDS,
    capacity_status,
    load_real_world_validation,
    load_real_world_validation_for_production_scoring,
    split_leakage_report,
    validate_contract,
)

_V01 = Path(__file__).parent / "gold" / "real_world_validation" / "v01"
_APP = Path(__file__).resolve().parents[1] / "app"


def _copy_corpus(tmp_path: Path) -> Path:
    dest = tmp_path / "corpus"
    shutil.copytree(_V01, dest)
    return dest


def _rewrite(path: Path, mutate) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_contract_fixture_loads_and_keeps_holdout_out_of_production() -> None:
    corpus = load_real_world_validation(_V01)
    assert corpus.manifest.contract_version == CONTRACT_VERSION
    assert corpus.manifest.dataset_version == DATASET_VERSION
    assert corpus.manifest.production_behavior_changed is False
    assert list(corpus.manifest.required_source_fields) == list(REQUIRED_SOURCE_FIELDS)
    assert {source.split for source in corpus.sources} == {"pilot", "dev", "blind"}
    scoring = load_real_world_validation_for_production_scoring(_V01)
    assert {row.split for row in scoring.sources} == {"pilot", "dev"}
    assert all(row.split != "blind" for row in scoring.judgments)
    status = capacity_status(corpus)
    assert status.meets_targets is False
    assert status.event_count >= 21
    assert status.profile_count == 50
    assert status.judgment_count == 3


def test_production_scoring_does_not_open_holdout_index(tmp_path: Path) -> None:
    dest = _copy_corpus(tmp_path)
    shutil.rmtree(dest / "blind")
    scoring = load_real_world_validation_for_production_scoring(dest)
    assert scoring.indexes.keys() == {"pilot", "dev"}
    with pytest.raises(FileNotFoundError):
        load_real_world_validation(dest)


def test_production_scoring_rejects_holdout_directory() -> None:
    with pytest.raises(ValueError, match="blind"):
        load_real_world_validation_for_production_scoring(_V01 / "blind")


def test_canonical_url_leakage_is_rejected(tmp_path: Path) -> None:
    dest = _copy_corpus(tmp_path)
    pilot_url = json.loads((dest / "sources.json").read_text(encoding="utf-8"))[0]["canonical_url"]

    def _leak(rows):
        for row in rows:
            if row["split"] == "dev":
                row["canonical_url"] = pilot_url

    _rewrite(dest / "sources.json", _leak)
    with pytest.raises(ValueError, match="canonical_url"):
        load_real_world_validation(dest)


def test_event_cross_split_and_mirror_leakage_are_rejected(tmp_path: Path) -> None:
    dest = _copy_corpus(tmp_path)

    def _point_dev_source_at_pilot_event(rows):
        for row in rows:
            if row["split"] == "dev":
                row["event_id"] = "evt_contract_p01"

    _rewrite(dest / "sources.json", _point_dev_source_at_pilot_event)
    with pytest.raises(ValueError, match="crosses event split"):
        load_real_world_validation(dest)

    dest = _copy_corpus(tmp_path / "mirror")

    def _mirror(rows):
        for row in rows:
            if row["split"] == "blind":
                row["mirror_group"] = "mg_contract_p01"

    _rewrite(dest / "events.json", _mirror)
    with pytest.raises(ValueError, match="mirror_group"):
        load_real_world_validation(dest)


def test_profile_and_redundancy_leakage_are_rejected(tmp_path: Path) -> None:
    dest = _copy_corpus(tmp_path)

    def _profile(rows):
        for row in rows:
            if row["split"] == "dev":
                row["profile_id"] = "prf_contract_p01"

    def _judgment_profile(rows):
        for row in rows:
            if row["split"] == "dev":
                row["profile_id"] = "prf_contract_p01"

    _rewrite(dest / "profiles.json", _profile)
    _rewrite(dest / "judgments" / "records.json", _judgment_profile)
    with pytest.raises(ValueError, match="profile_id"):
        load_real_world_validation(dest)

    dest = _copy_corpus(tmp_path / "redundancy")

    def _redundancy(rows):
        for row in rows:
            if row["split"] == "dev":
                row["redundancy_group"] = "rg_contract_p01"

    _rewrite(dest / "events.json", _redundancy)
    with pytest.raises(ValueError, match="redundancy_group"):
        load_real_world_validation(dest)


def test_content_hash_must_match_raw_evidence(tmp_path: Path) -> None:
    dest = _copy_corpus(tmp_path)

    def _break_hash(rows):
        rows[0]["content_hash"] = "0" * 64

    _rewrite(dest / "sources.json", _break_hash)
    with pytest.raises(ValueError, match="content_hash"):
        load_real_world_validation(dest)


def test_missing_source_field_fails_schema(tmp_path: Path) -> None:
    dest = _copy_corpus(tmp_path)

    def _drop(rows):
        rows[0].pop("evidence_locator")

    _rewrite(dest / "sources.json", _drop)
    with pytest.raises(ValidationError, match="evidence_locator"):
        load_real_world_validation(dest)


def test_holdout_ids_are_not_in_production_modules() -> None:
    from app.evaluation.personalization_gold import scan_python_sources

    holdout = json.loads((_V01 / "blind" / "index.json").read_text(encoding="utf-8"))
    tokens = {
        "tests/gold/real_world_validation/v01/blind",
        *holdout["source_ids"],
        *holdout["event_ids"],
        *holdout["profile_ids"],
        *holdout["judgment_ids"],
    }
    assert scan_python_sources(_APP, tokens) == ()


def test_split_report_is_clean_on_contract_fixture() -> None:
    corpus = load_real_world_validation(_V01)
    report = split_leakage_report(corpus)
    assert report.ok is True
    validate_contract(corpus)
