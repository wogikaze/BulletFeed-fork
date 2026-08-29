from __future__ import annotations

import json
import re
import runpy
from pathlib import Path

import pytest

from app.evaluation.personalization_gold import (
    DATASET_VERSION,
    LABEL_PROTOCOL_VERSION,
    evaluate_personalization,
    load_label_schema,
    load_personalization_gold,
    scan_python_sources,
    validate_judgment_against_schema,
)
from app.services.cold_start_policy import (
    IRRELEVANT_ITEM_RATE_CEILING,
    PRECISION_AT_5_FLOOR,
)
from app.services.user_interest import semantic_match, state_from_personalization_user

_V01 = Path(__file__).parent / "gold" / "personalization" / "v01"
_APP = Path(__file__).resolve().parents[1] / "app"
_LEAKAGE_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_personalization_gold_leakage.py"
_TOKEN_RE = re.compile(r"[a-z0-9.+-]+")


def _corpus():
    return load_personalization_gold(_V01)


def _schema() -> dict:
    return load_label_schema(_V01 / "label_schema.json")


def _tokenize(*parts: str) -> set[str]:
    tokens: set[str] = set()
    for part in parts:
        tokens.update(_TOKEN_RE.findall(part.lower()))
    return tokens


def _oracle_rankings(corpus) -> dict[str, list[str]]:
    rankings: dict[str, list[str]] = {}
    for user in corpus.users:
        judged = list(corpus.judgments_for_user(user.user_id))
        judged.sort(key=lambda row: (-row.relevance, -row.importance_to_user, row.item_id))
        rankings[user.user_id] = [row.item_id for row in judged]
    return rankings


def _lexical_rankings(corpus) -> dict[str, list[str]]:
    items = corpus.item_by_id()
    rankings: dict[str, list[str]] = {}
    for user in corpus.users:
        user_terms = _tokenize(
            user.profile.occupation,
            *user.profile.interests,
            *(topic.name for topic in user.topics),
            *(repo.full_name for repo in user.repositories),
            *user.products,
        )
        scored: list[tuple[int, str]] = []
        for judgment in corpus.judgments_for_user(user.user_id):
            item = items[judgment.item_id]
            blob = f"{item.title} {item.summary} {' '.join(item.tokens)}"
            text = blob.lower()
            score = 0
            for term in user_terms:
                if not term:
                    continue
                if term in text or any(term in token or token in term for token in _tokenize(blob)):
                    score += 1
            scored.append((score, item.item_id))
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        rankings[user.user_id] = [item_id for _, item_id in scored]
    return rankings


def test_schema_validation_and_versions_are_present() -> None:
    schema = _schema()
    corpus = _corpus()
    raw_judgments = json.loads((_V01 / "judgments.json").read_text(encoding="utf-8"))

    assert schema["label_protocol_version"] == LABEL_PROTOCOL_VERSION
    assert schema["dataset_version"] == DATASET_VERSION
    assert corpus.dataset_version == DATASET_VERSION
    assert corpus.label_protocol_version == LABEL_PROTOCOL_VERSION
    assert raw_judgments
    for raw in raw_judgments:
        validate_judgment_against_schema(raw, schema)
        assert raw["label_protocol_version"] == LABEL_PROTOCOL_VERSION
        assert raw["dataset_version"] == DATASET_VERSION
        assert raw["split"] in {"pilot", "blind"}
        assert 0 <= raw["relevance"] <= 3
        assert 0 <= raw["importance_to_user"] <= 3
        assert isinstance(raw["should_surface"], bool)
        assert raw["redundancy_group"]
        assert raw["rationale"]
        assert raw["provenance"]


def test_corpus_meets_size_and_source_family_floors() -> None:
    corpus = _corpus()
    manifest = json.loads((_V01 / "gold_manifest_v01.json").read_text(encoding="utf-8"))
    families = corpus.source_families()

    assert len(corpus.users) >= 20
    assert len(corpus.judgments) >= 300
    assert len(families) >= 4
    assert "github_release" in families
    assert "statuspage" in families
    assert families & {"github_advisory", "osv"}
    assert families & {"rss_atom", "json_feed"}
    assert len(corpus.users) >= manifest["minimum_users"]
    assert len(corpus.judgments) >= manifest["minimum_judgments"]
    assert {"cold_start", "history_rich"} <= {user.kind for user in corpus.users}
    assert any(not user.topics for user in corpus.users)
    assert any(user.topics and user.repositories and user.prior_feedback for user in corpus.users)
    for user in corpus.users:
        assert user.profile.occupation
        assert user.profile.region is not None


def test_pilot_and_holdout_ids_are_partitioned() -> None:
    corpus = _corpus()
    pilot = json.loads((_V01 / "pilot" / "index.json").read_text(encoding="utf-8"))
    holdout = json.loads((_V01 / "blind" / "index.json").read_text(encoding="utf-8"))

    assert set(pilot["user_ids"]).isdisjoint(holdout["user_ids"])
    assert set(pilot["item_ids"]).isdisjoint(holdout["item_ids"])
    assert set(pilot["judgment_ids"]).isdisjoint(holdout["judgment_ids"])
    assert set(pilot["bundle_ids"]).isdisjoint(holdout["bundle_ids"])
    assert {user.user_id for user in corpus.for_split("pilot").users} == set(pilot["user_ids"])
    assert {user.user_id for user in corpus.for_split("blind").users} == set(holdout["user_ids"])
    assert {row.judgment_id for row in corpus.for_split("pilot").judgments} == set(pilot["judgment_ids"])
    assert {row.judgment_id for row in corpus.for_split("blind").judgments} == set(holdout["judgment_ids"])


def test_hard_negatives_exist_and_lexical_baseline_does_not_ace_gate() -> None:
    corpus = _corpus().for_split("pilot")
    hard = [row for row in corpus.judgments if row.hard_negative]
    assert hard
    assert all(row.relevance == 0 and row.should_surface is False for row in hard)
    assert any("react" in row.rationale.lower() or "lexical" in row.rationale.lower() for row in hard)

    oracle = evaluate_personalization(corpus, _oracle_rankings(corpus), k=5, split="pilot")
    lexical = evaluate_personalization(corpus, _lexical_rankings(corpus), k=5, split="pilot")
    assert oracle.include_ambiguous.ndcg_at_k >= 0.90
    assert lexical.include_ambiguous.ndcg_at_k < oracle.include_ambiguous.ndcg_at_k
    assert lexical.include_ambiguous.precision_at_k < 0.80
    assert lexical.include_ambiguous.ndcg_at_k < 0.85

    react_user = next(
        user.user_id
        for user in corpus.users
        if "react" in user.products and user.kind == "history_rich"
    )
    hard_ids = {row.item_id for row in corpus.judgments if row.user_id == react_user and row.hard_negative}
    assert hard_ids
    lexical_top = _lexical_rankings(corpus)[react_user][:3]
    oracle_top = _oracle_rankings(corpus)[react_user][:3]
    assert hard_ids & set(lexical_top)
    assert not hard_ids & set(oracle_top)


def test_evaluator_reports_cold_start_slice_metrics_with_floors() -> None:
    corpus = _corpus().for_split("pilot")
    report = evaluate_personalization(corpus, _oracle_rankings(corpus), k=5, split="pilot")

    assert {"cold_start", "history_rich"} <= set(report.slices)
    cold = report.slices["cold_start"]
    rich = report.slices["history_rich"]
    assert cold.slice_name == "cold_start"
    assert cold.user_count >= 1
    assert rich.user_count >= 1
    assert cold.user_count + rich.user_count == report.include_ambiguous.user_count
    assert 0.0 <= cold.irrelevant_item_rate <= 1.0
    assert cold.precision_at_k >= PRECISION_AT_5_FLOOR
    assert cold.irrelevant_item_rate <= IRRELEVANT_ITEM_RATE_CEILING
    assert any(user.kind == "cold_start" and not user.topics for user in corpus.users)
    assert any(
        row.hard_negative and corpus.user_by_id()[row.user_id].kind == "cold_start"
        for row in corpus.judgments
    ) or any(row.hard_negative for row in corpus.judgments)


def test_evaluator_computes_precision_recall_ndcg_and_redundancy() -> None:
    corpus = _corpus().for_split("pilot")
    report = evaluate_personalization(corpus, _oracle_rankings(corpus), k=10, split="pilot")

    metrics = report.include_ambiguous
    assert report.k == 10
    assert metrics.k == 10
    assert 0.0 <= metrics.precision_at_k <= 1.0
    assert 0.0 <= metrics.recall_at_k <= 1.0
    assert 0.0 <= metrics.ndcg_at_k <= 1.0
    assert 0.0 <= metrics.redundancy_at_k <= 1.0
    assert metrics.user_count == len(corpus.users)
    assert metrics.judgment_count == len(corpus.judgments)
    assert metrics.precision_at_k > 0
    assert metrics.recall_at_k > 0
    assert metrics.ndcg_at_k > 0
    assert report.exclude_ambiguous.judgment_count <= metrics.judgment_count


def test_evaluator_reports_unresolved_ambiguous_separately() -> None:
    corpus = _corpus().for_split("blind")
    ambiguous = [row for row in corpus.judgments if row.ambiguous]
    assert ambiguous
    report = evaluate_personalization(corpus, _oracle_rankings(corpus), k=5, split="blind")
    assert report.unresolved_ambiguous_count == len(ambiguous)
    assert report.exclude_ambiguous.judgment_count == len(corpus.judgments) - len(ambiguous)
    assert report.include_ambiguous.judgment_count == len(corpus.judgments)


def test_blind_leakage_guard_for_production_app() -> None:
    holdout = json.loads((_V01 / "blind" / "index.json").read_text(encoding="utf-8"))
    forbidden = {
        "tests/gold/personalization/v01/blind",
        "gold/personalization/v01/blind",
        *holdout["bundle_ids"],
        *holdout["user_ids"],
        *holdout["item_ids"],
        *holdout["judgment_ids"],
    }
    assert scan_python_sources(_APP, forbidden) == ()

    try:
        runpy.run_path(str(_LEAKAGE_SCRIPT), run_name="__main__")
    except SystemExit as exc:
        assert exc.code in (0, None)


def _semantic_rankings(corpus) -> dict[str, list[str]]:
    items = corpus.item_by_id()
    rankings: dict[str, list[str]] = {}
    for user in corpus.users:
        state = state_from_personalization_user(
            user.user_id,
            occupation=user.profile.occupation,
            interests=user.profile.interests,
            topics=tuple((topic.name, topic.priority) for topic in user.topics),
            repositories=tuple((repo.full_name, repo.language) for repo in user.repositories),
            prior_feedback=tuple((row.summary, row.feedback) for row in user.prior_feedback),
        )
        scored: list[tuple[float, str]] = []
        for judgment in corpus.judgments_for_user(user.user_id):
            item = items[judgment.item_id]
            blob = f"{item.title} {item.summary} {' '.join(item.tokens)}"
            scored.append((semantic_match(state, blob).score, item.item_id))
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        rankings[user.user_id] = [item_id for _, item_id in scored]
    return rankings


def test_neighbor_aware_interest_matcher_reports_precision_recall_gain() -> None:
    corpus = _corpus().for_split("pilot")
    exact = evaluate_personalization(corpus, _lexical_rankings(corpus), k=5, split="pilot")
    semantic = evaluate_personalization(corpus, _semantic_rankings(corpus), k=5, split="pilot")

    assert semantic.include_ambiguous.precision_at_k > exact.include_ambiguous.precision_at_k
    assert semantic.include_ambiguous.recall_at_k > exact.include_ambiguous.recall_at_k
    assert semantic.include_ambiguous.precision_at_k > 0
    assert semantic.include_ambiguous.recall_at_k > 0

    react_user = next(
        user.user_id
        for user in corpus.users
        if "react" in user.products and user.kind == "history_rich"
    )
    hard_ids = {row.item_id for row in corpus.judgments if row.user_id == react_user and row.hard_negative}
    assert hard_ids
    assert hard_ids & set(_lexical_rankings(corpus)[react_user][:3])
    assert not hard_ids & set(_semantic_rankings(corpus)[react_user][:3])


def test_schema_rejects_out_of_range_relevance() -> None:
    schema = _schema()
    raw = json.loads((_V01 / "pilot" / "judgments.json").read_text(encoding="utf-8"))[0]
    raw["relevance"] = 4
    with pytest.raises(ValueError, match="above maximum"):
        validate_judgment_against_schema(raw, schema)
