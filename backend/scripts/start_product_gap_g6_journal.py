"""Create an empty G6 journal. This is the start of the 7-day clock, not completion."""

from __future__ import annotations

import json
from pathlib import Path

from app.evaluation.product_gap_c1 import load_g0_sources
from app.evaluation.product_gap_g6 import start_g6_journal

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "tests" / "gold" / "product_gap" / "c1" / "sources.json"
OUT = ROOT / "tests" / "gold" / "product_gap" / "c1" / "g6_journal.json"


def _payload(row) -> dict:
    return {
        "source_id": row.source_id,
        "site_url": row.site_url,
        "language": row.language,
        "family": row.family,
    }


def main() -> int:
    rows = [row for row in load_g0_sources(SOURCES) if row.policy_status == "eligible"]
    selected = []
    seen: set[str] = set()
    for row in rows:
        if row.language == "ja" and len([item for item in selected if item["language"] == "ja"]) < 40:
            selected.append(_payload(row))
            seen.add(row.source_id)
    families = {item["family"] for item in selected}
    for row in rows:
        if row.source_id in seen:
            continue
        if row.family not in families and len(families) < 5:
            selected.append(_payload(row))
            seen.add(row.source_id)
            families.add(row.family)
        if len(selected) >= 100 and len(families) >= 5:
            break
    for row in rows:
        if len(selected) >= 100:
            break
        if row.source_id in seen:
            continue
        selected.append(_payload(row))
        seen.add(row.source_id)
    start_g6_journal(OUT, sources=selected)
    print(
        json.dumps(
            {
                "wrote": str(OUT),
                "sources": len(selected),
                "japanese": sum(1 for item in selected if item["language"] == "ja"),
                "families": sorted({item["family"] for item in selected}),
                "close": False,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
