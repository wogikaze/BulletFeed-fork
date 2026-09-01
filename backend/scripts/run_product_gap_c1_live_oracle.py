"""Write the dev-only G3 live RSS oracle parity artifact."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from app.evaluation.product_gap_c1_live_oracle import measure_live_g3

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "tests" / "gold" / "product_gap" / "c1" / "v2"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--delay", type=float, default=0.10)
    parser.add_argument(
        "--output",
        type=Path,
        default=GOLD / "measurements" / "g3_measurement.json",
    )
    args = parser.parse_args(argv)
    report = asyncio.run(
        measure_live_g3(
            GOLD,
            limit=args.limit,
            timeout_seconds=args.timeout,
            delay_seconds=args.delay,
        )
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "selected_sources": report["selected_sources"],
                "attempted_sources": report["attempted_sources"],
                "successful_sources": report["successful_sources"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
