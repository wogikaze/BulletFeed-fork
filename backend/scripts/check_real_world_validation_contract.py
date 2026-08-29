"""Validate the #117 Phase 0 corpus contract and holdout isolation.

Does not run production rankers. Full 2,000-judgment evaluation is out of band.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.evaluation.personalization_gold import scan_python_sources
from app.evaluation.real_world_validation import (
    capacity_status,
    coverage_inventory,
    load_real_world_validation,
    load_real_world_validation_for_production_scoring,
)

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "backend" / "tests" / "gold" / "real_world_validation" / "v01"
APP = ROOT / "backend" / "app"


def _holdout_tokens() -> frozenset[str]:
    index = json.loads((CORPUS / "blind" / "index.json").read_text(encoding="utf-8"))
    tokens = {
        "tests/gold/real_world_validation/v01/blind",
        *index.get("source_ids", []),
        *index.get("event_ids", []),
        *index.get("profile_ids", []),
        *index.get("judgment_ids", []),
    }
    return frozenset(token for token in tokens if token)


def main() -> None:
    corpus = load_real_world_validation(CORPUS)
    leaks = scan_python_sources(APP, _holdout_tokens())
    if leaks:
        raise SystemExit("real-world validation holdout leaked into production:\n" + "\n".join(leaks))
    scoring = load_real_world_validation_for_production_scoring(CORPUS)
    scoring_rows = scoring.sources + scoring.events + scoring.profiles + scoring.judgments
    if any(row.split == "blind" for row in scoring_rows):
        raise SystemExit("production-scoring loader returned a blind record")
    status = capacity_status(corpus)
    coverage = coverage_inventory(corpus)
    print(
        "real-world validation contract OK: "
        f"real_events={status.real_event_count} events={status.event_count} "
        f"profiles={status.profile_count} judgments={status.judgment_count} "
        f"persona_templates={status.persona_template_count} "
        f"capacity_met={status.meets_targets} coverage={coverage}"
    )


if __name__ == "__main__":
    main()
