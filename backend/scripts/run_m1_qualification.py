"""Run the deterministic 30-persona M1 qualification harness."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from app.database import Database
from app.evaluation.m1_zero_to_useful import (
    PERSONA_MANIFEST_VERSION,
    load_persona_manifest,
    run_qualification,
)

PERSONA_MANIFEST = (
    Path(__file__).resolve().parents[1]
    / "tests"
    / "gold"
    / "m1_personas"
    / "v01"
    / "personas.json"
)


def _database_factory(root: Path):
    index = 0

    def create() -> Database:
        nonlocal index
        index += 1
        database = Database(root / f"persona-{index}.db")
        database.initialize()
        return database

    return create


def _write_report(report: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    personas = load_persona_manifest(PERSONA_MANIFEST)
    if len(personas) < 30:
        raise ValueError(f"M1 requires at least 30 personas, got {len(personas)}")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
        report = run_qualification(
            _database_factory(Path(directory)),
            personas,
        )
    report["mode"] = "deterministic_fixture"
    report["persona_manifest"] = PERSONA_MANIFEST.relative_to(PERSONA_MANIFEST.parents[3]).as_posix()
    report["persona_manifest_version"] = PERSONA_MANIFEST_VERSION
    if args.output is not None:
        _write_report(report, args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    failed = (
        report["failed_persona_ids"]
        or report["unexpected_empty_feed"]
        or report["broken_evidence"]
        or report["tenant_leak"]
        or report["unsafe_suppression"]
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
