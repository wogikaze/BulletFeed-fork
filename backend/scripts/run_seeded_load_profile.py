"""Write a versioned seeded load profile. No live network."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.database import Database
from app.evaluation.seeded_load_profile import run_seeded_load_profile, write_report

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "tests" / "gold" / "seeded_load" / "v01" / "latest_profile.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--incidents", type=int, default=40)
    parser.add_argument("--updates", type=int, default=4)
    parser.add_argument("--users", type=int, default=3)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--database", type=Path, default=None)
    args = parser.parse_args(argv)
    database_path = args.database or Path(args.output).with_suffix(".db")
    if database_path.exists():
        database_path.unlink()
    database = Database(database_path)
    database.initialize()
    report = run_seeded_load_profile(
        database,
        incident_count=args.incidents,
        updates_per_incident=args.updates,
        user_count=args.users,
    )
    write_report(report, args.output)
    print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
