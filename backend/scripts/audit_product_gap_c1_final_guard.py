"""Audit whether the one-shot final blind preflight is unlocked."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.evaluation.product_gap_c1_final_guard import audit_final_blind_preflight

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "tests" / "gold" / "product_gap" / "c1" / "v2"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold-dir", type=Path, default=GOLD)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    report = audit_final_blind_preflight(args.gold_dir)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.check and not report["ready"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
