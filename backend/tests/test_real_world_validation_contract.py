from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.evaluation.real_world_validation import (
    CONTRACT_VERSION,
    DATASET_VERSION,
    PERSONA_INDEPENDENCE_NOTE,
    REQUIRED_SOURCE_FIELDS,
    EventRecord,
    SourceRecord,
    capacity_status,
    load_real_world_validation,
    load_real_world_validation_for_production_scoring,
    production_scoring_record_paths,
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
    assert corpus.manifest.persona_independence_note == PERSONA_INDEPENDENCE_NOTE
    assert {source.split for source in corpus.sources} == {"pilot", "dev", "blind"}
    scoring = load_real_world_validation_for_production_scoring(_V01)
    assert {row.split for row in scoring.sources} == {"pilot", "dev"}
    assert all(row.split != "blind" for row in scoring.judgments)
    status = capacity_status(corpus)
    assert status.meets_targets is False
    assert status.real_event_count == 10
    assert status.real_event_count < 21
    assert status.event_count == 13
    assert status.profile_count == 50
    assert status.judgment_count == 3
    assert status.persona_template_count == 8


def test_production_scoring_paths_never_include_blind() -> None:
    paths = production_scoring_record_paths(_V01)
    assert paths[0] == _V01 / "manifest.json"
    assert all("blind" not in path.parts for path in paths)
    assert any(path.parts[-2] == "pilot" for path in paths)
    assert any(path.parts[-2] == "dev" for path in paths)


def test_production_scoring_does_not_open_or_read_blind_files(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []
    real_read_text = Path.read_text
    real_read_bytes = Path.read_bytes

    def _guard_text(self: Path, *args, **kwargs):
        opened.append(str(self))
        if "blind" in self.parts:
            raise AssertionError(f"production scoring opened a blind path: {self}")
        return real_read_text(self, *args, **kwargs)

    def _guard_bytes(self: Path, *args, **kwargs):
        opened.append(str(self))
        if "blind" in self.parts:
            raise AssertionError(f"production scoring opened a blind path: {self}")
        return real_read_bytes(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _guard_text)
    monkeypatch.setattr(Path, "read_bytes", _guard_bytes)
    scoring = load_real_world_validation_for_production_scoring(_V01)
    assert scoring.indexes.keys() == {"pilot", "dev"}
    assert all("blind" not in Path(path).parts for path in opened)


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


def test_missing_or_invalid_split_is_not_silently_dropped(tmp_path: Path) -> None:
    dest = _copy_corpus(tmp_path)

    def _drop_split(rows):
        rows[0].pop("split")

    _rewrite(dest / "pilot" / "sources.json", _drop_split)
    with pytest.raises(ValidationError, match="split"):
        load_real_world_validation(dest)

    dest = _copy_corpus(tmp_path / "invalid")

    def _bad_split(rows):
        rows[0]["split"] = "train"

    _rewrite(dest / "pilot" / "sources.json", _bad_split)
    with pytest.raises(ValidationError):
        load_real_world_validation(dest)


def test_canonical_url_leakage_is_rejected(tmp_path: Path) -> None:
    dest = _copy_corpus(tmp_path)
    pilot_url = json.loads((dest / "pilot" / "sources.json").read_text(encoding="utf-8"))[0]["canonical_url"]

    def _leak(rows):
        rows[0]["canonical_url"] = pilot_url

    _rewrite(dest / "dev" / "sources.json", _leak)
    with pytest.raises(ValueError, match="canonical_url"):
        load_real_world_validation(dest)


def test_event_cross_split_and_mirror_leakage_are_rejected(tmp_path: Path) -> None:
    dest = _copy_corpus(tmp_path)

    def _point_dev_source_at_pilot_event(rows):
        for row in rows:
            if row["source_role"] == "contract_fixture":
                row["event_id"] = "evt_contract_p01"

    _rewrite(dest / "dev" / "sources.json", _point_dev_source_at_pilot_event)
    with pytest.raises(ValueError, match="crosses event split"):
        load_real_world_validation(dest)

    dest = _copy_corpus(tmp_path / "mirror")

    def _mirror(rows):
        for row in rows:
            if row["record_kind"] == "contract_fixture":
                row["mirror_group"] = "mg_evt_contract_p01"

    _rewrite(dest / "blind" / "events.json", _mirror)
    with pytest.raises(ValueError, match="mirror_group"):
        load_real_world_validation(dest)


def test_profile_and_redundancy_leakage_are_rejected(tmp_path: Path) -> None:
    dest = _copy_corpus(tmp_path)

    def _profile(rows):
        rows[0]["profile_id"] = "prf_contract_p01"

    def _judgment_profile(rows):
        rows[0]["profile_id"] = "prf_contract_p01"

    _rewrite(dest / "dev" / "profiles.json", _profile)
    _rewrite(dest / "dev" / "judgments.json", _judgment_profile)
    with pytest.raises(ValueError, match="profile_id"):
        load_real_world_validation(dest)

    dest = _copy_corpus(tmp_path / "redundancy")

    def _redundancy(rows):
        for row in rows:
            if row["record_kind"] == "contract_fixture":
                row["redundancy_group"] = "rg_evt_contract_p01"

    _rewrite(dest / "dev" / "events.json", _redundancy)
    with pytest.raises(ValueError, match="redundancy_group"):
        load_real_world_validation(dest)


def test_content_hash_must_match_saved_artifact(tmp_path: Path) -> None:
    dest = _copy_corpus(tmp_path)

    def _break_hash(rows):
        rows[0]["content_hash"] = "0" * 64

    _rewrite(dest / "pilot" / "sources.json", _break_hash)
    with pytest.raises(ValueError, match="content_hash"):
        load_real_world_validation(dest)


def test_evidence_text_must_be_inside_artifact(tmp_path: Path) -> None:
    dest = _copy_corpus(tmp_path)

    def _invent_summary(rows):
        rows[0]["evidence_text"] = "This one-line summary was written by an evaluator, not fetched."

    _rewrite(dest / "pilot" / "sources.json", _invent_summary)
    with pytest.raises(ValueError, match="evidence_text"):
        load_real_world_validation(dest)


def test_placeholder_occurred_at_is_rejected() -> None:
    with pytest.raises(ValidationError, match="placeholder"):
        EventRecord.model_validate(
            {
                "event_id": "evt_dummy",
                "split": "pilot",
                "title": "Dummy",
                "information_type": "release",
                "language": "en",
                "redundancy_group": "rg_dummy",
                "mirror_group": "mg_dummy",
                "record_kind": "event_update",
                "is_real_event": True,
                "occurred_at": "2024-08-01T00:00:00Z",
                "occurred_at_provenance": "github_release.published_at",
                "occurred_at_basis": "2024-08-01T00:00:00Z",
                "provenance": "dummy",
            }
        )


def test_discovery_endpoint_is_not_a_real_event() -> None:
    source = SourceRecord.model_validate(
        {
            "source_id": "src_discovery_example",
            "canonical_url": "https://github.blog/changelog/",
            "publisher": "GitHub Blog",
            "source_family": "official_changelog",
            "information_type": "roadmap_changelog",
            "language": "en",
            "collected_at": "2026-08-29T00:00:00Z",
            "content_hash": "a" * 64,
            "evidence_locator": "discovery-index",
            "event_id": None,
            "split": "pilot",
            "source_role": "discovery_endpoint",
            "fetch": {
                "fetch_kind": "live_https",
                "url": "https://github.blog/changelog/",
                "requested_at": "2026-08-29T00:00:00Z",
                "http_status": 200,
                "content_type": "text/html",
                "final_url": "https://github.blog/changelog/",
                "etag": None,
                "last_modified": None,
                "artifact_relpath": "artifacts/src_discovery_example/body.bin",
            },
            "evidence_text": "changelog index",
            "normalized_evidence": "GitHub Changelog index",
        }
    )
    assert source.event_id is None


def test_missing_source_field_fails_schema(tmp_path: Path) -> None:
    dest = _copy_corpus(tmp_path)

    def _drop(rows):
        rows[0].pop("evidence_locator")

    _rewrite(dest / "pilot" / "sources.json", _drop)
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
    validate_contract(corpus, corpus_dir=_V01)
