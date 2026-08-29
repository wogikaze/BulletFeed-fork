from __future__ import annotations

import inspect
import json
from pathlib import Path

from app.services.event_concepts import (
    EVENT_CONCEPT_VERSION,
    EventConceptExtraction,
    extract_event_concepts,
    extraction_from_snapshot,
    features_for_relation,
    rebuild_event_concepts,
    to_snapshot,
)
from app.services.relation import consume_concept_features, evaluate_relation

_GOLD = Path(__file__).parent / "gold" / "event_concepts" / "v01"


def _index() -> dict:
    return json.loads((_GOLD / "index.json").read_text(encoding="utf-8"))


def _cases() -> list[dict]:
    return json.loads((_GOLD / "cases.json").read_text(encoding="utf-8"))


def _by_id(concept_id: str, extraction: EventConceptExtraction):
    return next((item for item in extraction.concepts if item.concept_id == concept_id), None)


def _matches_expected_concept(extraction: EventConceptExtraction, expected: dict) -> bool:
    for concept in extraction.concepts:
        if expected.get("concept_id") and concept.concept_id != expected["concept_id"]:
            continue
        if expected.get("canonical_name") and concept.canonical_name != expected["canonical_name"]:
            continue
        if expected.get("stable_id") and concept.stable_id != expected["stable_id"]:
            continue
        if expected.get("product_version") and concept.product_version != expected["product_version"]:
            continue
        if expected.get("min_weight") is not None and concept.weight < float(expected["min_weight"]):
            continue
        aliases = expected.get("aliases_contain") or []
        if aliases and not all(alias in concept.aliases for alias in aliases):
            continue
        return True
    return False


def test_gold_manifest_versions_and_categories() -> None:
    index = _index()
    cases = _cases()
    categories = {str(case["category"]) for case in cases}

    assert index["extractor_version"] == EVENT_CONCEPT_VERSION
    assert index["dataset_version"] == EVENT_CONCEPT_VERSION
    assert index["rebuild"] == "deterministic"
    assert set(index["categories"]) == categories
    assert len(cases) >= 12
    for required in (
        "aliases",
        "ambiguous_names",
        "versioned_products",
        "lexical_collisions",
        "structured_override",
        "multi_weighted",
    ):
        assert required in categories


def test_gold_cases_extract_expected_concepts_and_abstentions() -> None:
    for case in _cases():
        extraction = extract_event_concepts(case["input"])
        expect = case["expect"]
        assert extraction.version == EVENT_CONCEPT_VERSION
        assert extraction.event_id == case["input"]["event_id"]
        assert all(EVENT_CONCEPT_VERSION in concept.provenance for concept in extraction.concepts)

        if expect.get("min_concepts") is not None:
            assert len(extraction.concepts) >= int(expect["min_concepts"]), case["id"]
        for expected in expect.get("concepts") or []:
            assert _matches_expected_concept(extraction, expected), (
                case["id"],
                expected,
                extraction.to_snapshot(),
            )
        for concept_id in expect.get("concept_ids_absent") or []:
            assert _by_id(concept_id, extraction) is None, case["id"]
        stable_ids = {concept.stable_id for concept in extraction.concepts}
        for stable_id in expect.get("stable_ids_absent") or []:
            assert stable_id not in stable_ids, case["id"]
        for expected in expect.get("abstentions") or []:
            matched = []
            for item in extraction.abstentions:
                candidate_ok = (
                    not expected.get("candidate_concept_id")
                    or item.candidate_concept_id == expected["candidate_concept_id"]
                )
                reason_ok = not expected.get("reason") or item.reason == expected["reason"]
                raw_ok = (
                    not expected.get("raw_contains")
                    or expected["raw_contains"].casefold() in item.raw_text.casefold()
                )
                if candidate_ok and reason_ok and raw_ok:
                    matched.append(item)
            assert matched, (case["id"], expected, extraction.to_snapshot())


def test_optional_rebuild_snapshot_matches_extractor() -> None:
    snapshot = json.loads((_GOLD / "rebuild_snapshot.json").read_text(encoding="utf-8"))
    assert snapshot["extractor_version"] == EVENT_CONCEPT_VERSION
    by_id = {case["id"]: case["extraction"] for case in snapshot["cases"]}
    assert set(by_id) == {case["id"] for case in _cases()}
    for case in _cases():
        rebuilt = rebuild_event_concepts(case["input"]).to_snapshot()
        assert rebuilt == by_id[case["id"]], case["id"]


def test_extraction_is_deterministically_rebuildable() -> None:
    case = next(item for item in _cases() if item["id"] == "multi-weighted-advisory-001")
    first = extract_event_concepts(case["input"])
    second = rebuild_event_concepts(case["input"])
    assert first.to_snapshot() == second.to_snapshot()
    assert to_snapshot(first)["version"] == EVENT_CONCEPT_VERSION


def test_snapshot_roundtrip_preserves_relation_features() -> None:
    case = next(item for item in _cases() if item["id"] == "structured-cve-override-001")
    extracted = extract_event_concepts(case["input"])
    restored = extraction_from_snapshot(extracted.to_snapshot())
    assert restored.to_snapshot() == extracted.to_snapshot()
    assert features_for_relation(restored).to_snapshot() == extracted.features_for_relation().to_snapshot()


def test_alias_normalization_preserves_raw_source_text() -> None:
    extraction = extract_event_concepts(
        {
            "event_id": "evt-raw-alias",
            "title": "k8s control plane patch",
            "summary": "Operators running Kubernetes should upgrade.",
        }
    )
    kubernetes = _by_id("kubernetes", extraction)
    assert kubernetes is not None
    assert "k8s" in kubernetes.aliases
    assert kubernetes.canonical_name == "Kubernetes"


def test_ambiguous_concepts_can_abstain() -> None:
    extraction = extract_event_concepts(
        {
            "title": "Java island earthquake status",
            "summary": "Aftershocks continue on the island of Java.",
        }
    )
    assert _by_id("java", extraction) is None
    assert any(item.candidate_concept_id == "java" for item in extraction.abstentions)


def test_one_event_can_have_multiple_weighted_concepts() -> None:
    extraction = extract_event_concepts(
        {
            "event_id": "evt-weights",
            "source_type": "github_advisory",
            "source_key": "GHSA-2c7m-w9v9-j2qh",
            "title": "GHSA-2c7m-w9v9-j2qh XSS in React server components",
            "summary": "Advisory for facebook/react.",
            "structured": {
                "ghsa_ids": ["GHSA-2c7m-w9v9-j2qh"],
                "repository": "facebook/react",
            },
        }
    )
    weights = {concept.concept_id: concept.weight for concept in extraction.concepts}
    assert weights["ghsa:GHSA-2C7M-W9V9-J2QH"] == 1.0
    assert weights["repo:facebook/react"] == 1.0
    assert weights["react"] >= 0.7
    assert weights["xss"] < weights["react"]
    assert len(extraction.concepts) >= 3


def test_structured_identifiers_override_weaker_prose() -> None:
    extraction = extract_event_concepts(
        {
            "title": "Writeup still cites CVE-2020-1111 and acme/widget",
            "summary": "Canonical record is CVE-2026-99999 for facebook/react.",
            "source_type": "osv",
            "structured": {
                "cve_ids": ["CVE-2026-99999"],
                "repository": "facebook/react",
            },
        }
    )
    stable_ids = {concept.stable_id for concept in extraction.concepts}
    assert "cve:CVE-2026-99999" in stable_ids
    assert "cve:CVE-2020-1111" not in stable_ids
    assert "repo:facebook/react" in stable_ids
    assert "repo:acme/widget" not in stable_ids
    assert any(item.reason == "structured_identifier_override" for item in extraction.abstentions)


def test_lexical_collisions_do_not_promote_unrelated_concepts() -> None:
    reactor = extract_event_concepts(
        {
            "title": "IAEA nuclear reactor inspection briefing",
            "summary": "Scheduled reactor containment inspection.",
        }
    )
    island = extract_event_concepts(
        {
            "title": "Java island earthquake status",
            "summary": "Aftershocks on the island of Java.",
        }
    )
    assert _by_id("react", reactor) is None
    assert _by_id("java", island) is None


def test_relation_consumes_concepts_without_reparsing_prose() -> None:
    extraction = extract_event_concepts(
        {
            "event_id": "evt-relation-features",
            "source_type": "github_release",
            "source_key": "facebook/react",
            "title": "React 19.1.0 released",
            "summary": "Compiler fixes for facebook/react.",
        }
    )
    features = extraction.features_for_relation()
    snapshot = features.to_snapshot()
    assert "title" not in snapshot
    assert "summary" not in snapshot
    assert "source_key" not in snapshot
    terms = consume_concept_features(features)
    assert "React" in terms
    assert "repo:facebook/react" in terms
    restored_terms = consume_concept_features(snapshot)
    assert restored_terms == terms


def test_evaluate_relation_behavior_is_unchanged(database) -> None:
    source = inspect.getsource(evaluate_relation)
    assert "extract_event_concepts" not in source
    assert "consume_concept_features" not in source
    assert "event_title" in source
    assert "event_summary" in source

    with database.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES ('user_rel', 0)")
        connection.execute(
            """
            INSERT INTO topics (
                id, user_id, name, type, priority, sort_order, created_at
            ) VALUES ('topic_kotlin', 'user_rel', 'Kotlin', 'technology', 'high', 0, 0)
            """
        )
        adjacent = evaluate_relation(
            connection,
            user_id="user_rel",
            source_type="rss_atom",
            source_key="https://engineering.example/feed.xml",
            event_title="Kotlin 2.3 migration guide",
            event_summary="Kotlin compiler migration guidance.",
        )
        reference = evaluate_relation(
            connection,
            user_id="user_rel",
            source_type="rss_atom",
            source_key="https://engineering.example/feed.xml",
            event_title="Office kitchen notes",
            event_summary="The espresso machine is back online.",
        )

    assert adjacent.level == "adjacent"
    assert adjacent.matched_topics == ("Kotlin",)
    assert adjacent.reason == "Matches one or more topics you follow."
    assert reference.level == "reference"
    assert reference.matched_topics == ()
    assert reference.reason == ""
