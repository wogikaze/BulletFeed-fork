"""Challenge-4 reason coverage and label-schema status."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from app.database import Database
from app.evaluation.m1_zero_to_useful import load_persona_manifest, run_qualification
from app.evaluation.product_gap_c4 import evaluate_c4

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "tests" / "gold" / "product_gap"
PERSONAS = ROOT / "tests" / "gold" / "m1_personas" / "v01" / "personas.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-m1", action="store_true")
    parser.add_argument("--output", type=Path, default=GOLD / "c4" / "measurement.json")
    args = parser.parse_args(argv)
    reason_missing = None
    m1: dict = {}
    if not args.skip_m1:
        personas = load_persona_manifest(PERSONAS)
        with TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            index = 0

            def factory() -> Database:
                nonlocal index
                index += 1
                database = Database(Path(directory) / f"p{index}.db")
                database.initialize()
                return database

            m1 = run_qualification(factory, personas)
            reason_missing = int(m1.get("display_reason_missing") or 0)
    report = evaluate_c4(GOLD / "c4", persona_reason_missing=reason_missing)
    report["m1"] = {"display_reason_missing": reason_missing, "persona_count": m1.get("persona_count")}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"pass": report["pass"], "output": str(args.output)}, indent=2))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
