"""Run real-network G1 source discovery measurement without touching blind by default."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from app.evaluation.product_gap_c1_live_discovery import measure_live_g1

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "tests" / "gold" / "product_gap" / "c1"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("dev", "blind"), default="dev")
    parser.add_argument("--allow-blind-final", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--delay", type=float, default=0.10)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    report = asyncio.run(
        measure_live_g1(
            GOLD,
            split=args.split,
            allow_blind_final=args.allow_blind_final,
            limit=args.limit,
            timeout_seconds=args.timeout,
            delay_seconds=args.delay,
        )
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
