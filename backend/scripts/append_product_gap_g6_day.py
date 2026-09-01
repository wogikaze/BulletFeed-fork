"""Append today's G6 observation row. Does not invent acquisition success."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JOURNAL = ROOT / "tests" / "gold" / "product_gap" / "c1" / "g6_journal.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acquisition-ok", type=int, default=0)
    parser.add_argument("--updates", type=int, default=0)
    parser.add_argument("--silent-miss", type=int, default=0)
    parser.add_argument("--stale-as-healthy", type=int, default=0)
    parser.add_argument("--unclassified", type=int, default=0)
    args = parser.parse_args(argv)
    payload = json.loads(JOURNAL.read_text(encoding="utf-8"))
    today = datetime.now(UTC).date().isoformat()
    days = payload.setdefault("days", [])
    existing = next((row for row in days if row.get("date") == today), None)
    row = {
        "date": today,
        "acquisition_ok": args.acquisition_ok,
        "updates": args.updates,
        "silent_miss": args.silent_miss,
        "stale_as_healthy": args.stale_as_healthy,
        "unclassified": args.unclassified,
    }
    if existing is None:
        days.append(row)
    else:
        existing.update(row)
    payload["observed_updates"] = sum(int(item.get("updates") or 0) for item in days)
    JOURNAL.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"date": today, "days": len(days), "updates": payload["observed_updates"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
