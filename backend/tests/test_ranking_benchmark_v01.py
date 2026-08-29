from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.evaluation.personalization_gold import (
    evaluate_personalization,
    load_personalization_gold,
    scan_python_sources,
)
from app.evaluation.ranking_benchmark import (
    BENCHMARK_VERSION,
    RANKING_CONTRACT_VERSION,
    build_ranking_snapshot,
    evaluate_ranking_benchmark,
    load_baseline_report,
    load_ranking_gold,
    product_rankings,
    ranking_regression_violations,
    require_ranking_regression_gate,
)

_GOLD = Path(__file__).parent / "gold" / "personalization" / "v01"
_BASELINE = Path(__file__).parent / "gold" / "ranking_benchmark" / "v01" / "pilot_baseline.json"
_SNAPSHOT = Path(__file__).parent / "gold" / "ranking_benchmark" / "v01" / "snapshot.json"
_APP = Path(__file__).resolve().parents[1] / "app"


def _corpus():
    return load_ranking_gold(_GOLD)


def _oracle_rankings(corpus) -> dict[str, list[str]]:
    rankings: dict[str, list[str]] = {}
    for user in corpus.users:
        judged = list(corpus.judgments_for_user(user.user_id))
        judged.sort(key=lambda row: (-row.relevance, -row.importance_to_user, row.item_id))
        rankings[user.user_id] = [row.item_id for row in judged]
    return rankings


def test_benchmark_loads_rec01_gold_without_rewriting_labels() -> None:
    snapshot = json.loads(_SNAPSHOT.read_text(encoding="utf-8"))
    users = (_GOLD / "users.json").read_bytes()
    items = (_GOLD / "items.json").read_bytes()
    judgments = (_GOLD / "judgments.json").read_bytes()

    corpus = _corpus()
    report = evaluate_ranking_benchmark(corpus, split="pilot")

    assert snapshot["labels_rewritten"] is False
    assert snapshot["dataset_version"] == corpus.dataset_version
    assert report.labels_rewritten is False
    assert report.label_source == corpus.dataset_version
    assert report.dataset_version == "personalization-v0.1"
    assert (_GOLD / "users.json").read_bytes() == users
    assert (_GOLD / "items.json").read_bytes() == items
    assert (_GOLD / "judgments.json").read_bytes() == judgments
    assert load_personalization_gold(_GOLD).judgments == corpus.judgments


def test_snapshot_is_reproducible_and_records_fixed_observations() -> None:
    corpus = _corpus()
    first = build_ranking_snapshot(corpus, split="pilot")
    second = build_ranking_snapshot(corpus, split="pilot")
    assert first == second
    assert first.ranking_contract_version == RANKING_CONTRACT_VERSION
    assert first.observation_ids == tuple(f"obs:{item_id}" for item_id in first.item_ids)
    assert first.user_kind_counts["cold_start"] >= 1
    assert first.user_kind_counts["history_rich"] >= 1
    assert len(first.fingerprint) == 64


def test_product_ranker_emits_precision_recall_ndcg_and_redundancy() -> None:
    corpus = _corpus()
    report = evaluate_ranking_benchmark(corpus, split="pilot")
    rankings = product_rankings(corpus.for_split("pilot"))
    gold_at_5 = evaluate_personalization(corpus.for_split("pilot"), rankings, k=5)
    gold_at_10 = evaluate_personalization(corpus.for_split("pilot"), rankings, k=10)

    assert report.benchmark_version == BENCHMARK_VERSION
    assert report.at_5.precision_at_k == gold_at_5.include_ambiguous.precision_at_k
    assert report.at_5.recall_at_k == gold_at_5.include_ambiguous.recall_at_k
    assert report.at_10.ndcg_at_k == gold_at_10.include_ambiguous.ndcg_at_k
    assert report.at_10.redundancy_at_k == gold_at_10.include_ambiguous.redundancy_at_k
    assert 0.0 <= report.at_5.precision_at_k <= 1.0
    assert 0.0 <= report.at_10.recall_at_k <= 1.0
    assert 0.0 <= report.at_10.ndcg_at_k <= 1.0
    assert 0.0 <= report.at_10.redundancy_at_k <= 1.0
    assert report.at_5.useful_in_top_k >= 0.0
    assert report.at_10.cards_to_first_useful >= 1.0
    assert 0.0 <= report.at_10.important_item_missed_rate <= 1.0
    assert 0.0 <= report.at_10.irrelevant_card_rate <= 1.0


def test_cold_start_and_history_rich_are_reported_separately() -> None:
    report = evaluate_ranking_benchmark(_corpus(), split="pilot")
    assert "cold_start" in report.by_kind
    assert "history_rich" in report.by_kind
    assert report.by_kind["cold_start"]["at_5"].user_count >= 1
    assert report.by_kind["history_rich"]["at_5"].user_count >= 1
    assert report.by_kind["cold_start"]["at_5"].user_count != report.at_5.user_count


def test_per_axis_diagnostics_are_emitted() -> None:
    report = evaluate_ranking_benchmark(_corpus(), split="pilot")
    names = {axis.axis for axis in report.axes}
    assert names == {
        "knownness_rank",
        "importance_rank",
        "relation_rank",
        "personalization_rank",
    }
    for axis in report.axes:
        assert 0.0 <= axis.precision_at_5 <= 1.0
        assert 0.0 <= axis.ndcg_at_10 <= 1.0


def test_oracle_outranks_product_so_labels_are_not_baked_into_the_algorithm() -> None:
    corpus = _corpus().for_split("pilot")
    product = evaluate_ranking_benchmark(corpus, split="pilot")
    oracle = evaluate_ranking_benchmark(corpus, split="pilot", predicted=_oracle_rankings(corpus))
    assert oracle.at_10.ndcg_at_k > product.at_10.ndcg_at_k
    assert oracle.at_5.precision_at_k > product.at_5.precision_at_k
    assert oracle.at_10.cards_to_first_useful < product.at_10.cards_to_first_useful


def test_checked_in_baseline_is_machine_readable_and_gates_regressions() -> None:
    corpus = _corpus()
    pilot = corpus.for_split("pilot")
    report = evaluate_ranking_benchmark(corpus, split="pilot")
    baseline = load_baseline_report(_BASELINE)
    assert baseline["benchmark_version"] == BENCHMARK_VERSION
    assert baseline["split"] == "pilot"
    assert baseline["labels_rewritten"] is False
    require_ranking_regression_gate(report, baseline)

    reversed_rankings = {
        user.user_id: list(reversed(_oracle_rankings(pilot)[user.user_id]))
        for user in pilot.users
    }
    broken = evaluate_ranking_benchmark(corpus, split="pilot", predicted=reversed_rankings)
    violations = ranking_regression_violations(broken, baseline)
    assert violations


def test_regression_gate_rejects_blind_split() -> None:
    report = evaluate_ranking_benchmark(_corpus(), split="blind")
    with pytest.raises(ValueError, match="pilot"):
        ranking_regression_violations(report, load_baseline_report(_BASELINE))


def test_blind_ids_are_not_hardcoded_in_production_app() -> None:
    holdout = json.loads((_GOLD / "blind" / "index.json").read_text(encoding="utf-8"))
    forbidden = {
        *holdout["bundle_ids"],
        *holdout["user_ids"],
        *holdout["item_ids"],
        *holdout["judgment_ids"],
    }
    assert scan_python_sources(_APP, forbidden) == ()
