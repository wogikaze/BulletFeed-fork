"""Validate the #117 Phase 0 corpus contract and holdout isolation.

Does not run production rankers. Full 2,000-judgment evaluation is out of band.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.evaluation.personalization_gold import scan_python_sources
from app.evaluation.real_world_validation import (
    capacity_status,
    load_real_world_validation,
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
    status = capacity_status(corpus)
    print(
        "real-world validation contract OK: "
        f"events={status.event_count} profiles={status.profile_count} "
        f"judgments={status.judgment_count} capacity_met={status.meets_targets}"
    )


if __name__ == "__main__":
    main()
