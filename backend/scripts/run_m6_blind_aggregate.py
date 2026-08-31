"""Run M6 #171 one-shot blind aggregate evaluation.

Evaluation-only. Production scoring paths are not imported. Do not retune.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parent
BACKEND = Path(__file__).resolve().parents[1]
CORPUS = BACKEND / "tests" / "gold" / "real_world_validation" / "v01"
OUTPUT = BACKEND / "tests" / "gold" / "m6" / "v01" / "oneshot_blind_aggregate.json"
FROZEN_PRODUCTION_SHA = "b1befc9ee4ab04eefe64820ca27332438f8946ce"


def _load_eval_module() -> Any:
    if str(_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS))
    import m6_blind_eval

    return m6_blind_eval


def _headline_at_10(report: dict[str, Any]) -> dict[str, Any]:
    return report["headline"]["include_ambiguous"]["at_10"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--repository-sha", default=FROZEN_PRODUCTION_SHA)
    args = parser.parse_args(argv)
    eval_mod = _load_eval_module()
    holdout = eval_mod.load_m6_blind_holdout(CORPUS)
    report = eval_mod.evaluate_m6_oneshot_blind(
        holdout,
        repository_sha=args.repository_sha,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "report_version": report["report_version"],
                "aggregate_status": report["aggregate_status"],
                "repository_sha": report["repository_sha"],
                "blind_read": report["blind_read"],
                "retune": report["retune"],
                "production_code_unchanged": report["production_code_unchanged"],
                "holdout": report["holdout"],
                "headline_at_10": _headline_at_10(report),
                "uncertainty_headline_at_10": report["uncertainty"]["headline"]["at_10"],
                "top3_persona_families": report["top3_persona_families"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
