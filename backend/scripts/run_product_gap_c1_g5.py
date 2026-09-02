"""Write the dev-only G5 production-fetch and identity measurement artifact."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from app.evaluation.product_gap_c1_g5_measurement import measure_live_g5

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "tests" / "gold" / "product_gap" / "c1" / "v2"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument(
        "--output",
        type=Path,
        default=GOLD / "measurements" / "g5_measurement.json",
    )
    args = parser.parse_args(argv)
    report = asyncio.run(measure_live_g5(GOLD, timeout_seconds=args.timeout))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "production_fetch_measured": report["production_fetch_measured"],
                "identity_measured": report["identity_measured"],
                "shape_bypass_count": report["shape_bypass_count"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
