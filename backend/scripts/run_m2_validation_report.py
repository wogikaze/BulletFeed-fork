"""Write a machine-readable M2 corpus and evaluation readiness report."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.evaluation.real_world_validation import (
    CONTRACT_VERSION,
    DATASET_VERSION,
    capacity_status,
    coverage_inventory,
    load_real_world_validation,
    load_real_world_validation_for_production_scoring,
)

CORPUS = Path(__file__).resolve().parents[1] / "tests" / "gold" / "real_world_validation" / "v01"


def _git_sha() -> str | None:
    git = shutil.which("git")
    if git is None:
        return None
    try:
        return (
            subprocess.check_output(
                [git, "rev-parse", "HEAD"],
                cwd=Path(__file__).resolve().parents[2],
                text=True,
            )  # noqa: S603
            .strip()
        )
    except (OSError, subprocess.CalledProcessError):
        return None


def _counts(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    return dict(sorted(Counter(str(row[key]) for row in rows).items()))


def build_report() -> dict[str, Any]:
    corpus = load_real_world_validation(CORPUS)
    status = capacity_status(corpus)
    production = load_real_world_validation_for_production_scoring(CORPUS)
    report = {
        "report_version": "m2-corpus-readiness-v1",
        "dataset_version": DATASET_VERSION,
        "contract_version": CONTRACT_VERSION,
        "frozen_main_sha": _git_sha(),
        "capacity": asdict(status),
        "coverage": coverage_inventory(corpus),
        "production_scoring": {
            "splits": sorted(production.indexes),
            "blind_records_loaded": False,
        },
        "splits": {},
        "judgments": {
            "label_source": "AI-silver",
            "human_gold": False,
            "by_stratum": _counts(
                [
                    row.model_dump()
                    for row in corpus.judgments
                    if row.split != "blind"
                ],
                "stratum",
            ),
        },
        "metrics": {
            "status": "not_evaluated",
            "note": "Production predictions, uncertainty, and stage attribution are M2-EVAL work.",
        },
    }
    for split in ("pilot", "dev", "blind"):
        scoped = corpus.for_split(split)
        report["splits"][split] = {
            "events": len(scoped.events),
            "real_events": len(scoped.real_events()),
            "sources": len(scoped.sources),
            "profiles": len(scoped.profiles),
            "judgments": len(scoped.judgments),
            "source_families": sorted({row.source_family for row in scoped.sources}),
            "languages": sorted({row.language for row in scoped.sources}),
            "persona_templates": sorted({row.persona_template for row in scoped.profiles}),
        }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    report = build_report()
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
