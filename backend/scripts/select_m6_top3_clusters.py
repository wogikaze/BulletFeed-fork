"""Select measured M6 ranking clusters and representative dev cases."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.evaluation.m2_validation_metrics import build_personalization_corpus
from app.evaluation.ranking_benchmark import rank_user_items
from app.evaluation.real_world_validation import (
    load_real_world_validation_for_production_scoring,
)

BACKEND = Path(__file__).resolve().parents[1]
CORPUS = BACKEND / "tests" / "gold" / "real_world_validation" / "v01"
M2_REPORT = CORPUS / "m2_readiness_report.json"
SELECTION_VERSION = "m6-top3-ranking-selection-v1"
MIN_REPRESENTATIVE_CASES = 20


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain an object")
    return payload


def _select_persona_families(report: dict[str, Any], limit: int) -> tuple[str, ...]:
    counts = report["metrics"]["failure_taxonomy"]["by_dimension"][
        "important_unknown_missed"
    ]["persona_family"]
    selected = sorted(
        (
            (str(family), int(count))
            for family, count in counts.items()
            if int(count) >= MIN_REPRESENTATIVE_CASES
        ),
        key=lambda item: (-item[1], item[0]),
    )
    if len(selected) < limit:
        raise ValueError(
            f"only {len(selected)} persona-family clusters meet the "
            f"{MIN_REPRESENTATIVE_CASES}-case minimum"
        )
    return tuple(family for family, _ in selected[:limit])


def select_clusters(
    *,
    report: dict[str, Any],
    corpus,
    representative_count: int,
    cluster_limit: int = 3,
) -> dict[str, Any]:
    if representative_count < MIN_REPRESENTATIVE_CASES:
        raise ValueError(f"representative_count must be >= {MIN_REPRESENTATIVE_CASES}")
    if cluster_limit < 1:
        raise ValueError("cluster_limit must be >= 1")
    adapted, metadata = build_personalization_corpus(corpus)
    item_by_id = adapted.item_by_id()
    known_before = {
        (row.profile_id, row.event_id): row.known_before
        for row in corpus.judgments
    }
    rankings = {
        user.user_id: rank_user_items(
            user,
            [
                item_by_id[judgment.item_id]
                for judgment in adapted.judgments_for_user(user.user_id)
            ],
        )
        for user in adapted.users
    }
    selected_families = _select_persona_families(report, cluster_limit)
    clusters = []
    for family in selected_families:
        cases = []
        for user in adapted.users:
            if user.profile.occupation != family:
                continue
            ranking = rankings.get(user.user_id, ())
            positions = {item_id: index + 1 for index, item_id in enumerate(ranking)}
            for judgment in adapted.judgments_for_user(user.user_id):
                is_known = known_before.get((user.user_id, judgment.item_id), False)
                if (
                    not judgment.should_surface
                    or is_known
                    or judgment.importance_to_user < 2
                    or positions.get(judgment.item_id, 11) <= 10
                ):
                    continue
                item = item_by_id[judgment.item_id]
                item_metadata = metadata[judgment.item_id]
                cases.append(
                    {
                        "case_id": judgment.judgment_id,
                        "profile_id": user.user_id,
                        "event_id": judgment.item_id,
                        "event_title": item.title,
                        "source_family": item_metadata.source_family,
                        "information_type": item_metadata.information_type,
                        "language": item_metadata.language,
                        "importance_to_user": judgment.importance_to_user,
                        "ranking_position": positions.get(judgment.item_id),
                        "earliest_stage": "ranking",
                        "rationale": judgment.rationale,
                    }
                )
        cases.sort(key=lambda row: (row["case_id"], row["profile_id"]))
        cluster_metrics = report["metrics"]["segments"]["persona_family"][family]
        clusters.append(
            {
                "persona_family": family,
                "failure": "important_unknown_missed",
                "failure_count": report["metrics"]["failure_taxonomy"][
                    "by_dimension"
                ]["important_unknown_missed"]["persona_family"][family],
                "representative_cases": cases[:representative_count],
                "representative_case_count": min(len(cases), representative_count),
                "available_case_count": len(cases),
                "metrics": cluster_metrics,
            }
        )
    return {
        "selection_version": SELECTION_VERSION,
        "status": "selected_for_dev_remediation",
        "label_source": "AI-silver",
        "human_gold": False,
        "blind_read": False,
        "selection_rule": (
            "Select the three persona-family clusters with the highest measured "
            "important-unknown ranking misses; retain deterministic representative "
            "cases only from pilot/dev production-scoring records."
        ),
        "stage_attribution": {
            "status": "ranking_only",
            "earliest_stage": "ranking",
            "uncovered_stages": ["acquisition", "projection", "evidence"],
        },
        "representative_case_minimum": MIN_REPRESENTATIVE_CASES,
        "clusters": clusters,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--m2-report", type=Path, default=M2_REPORT)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--representative-count", type=int, default=20)
    args = parser.parse_args(argv)
    report = _load_json(args.m2_report)
    corpus = load_real_world_validation_for_production_scoring(CORPUS)
    selected = select_clusters(
        report=report,
        corpus=corpus,
        representative_count=args.representative_count,
    )
    payload = json.dumps(selected, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
