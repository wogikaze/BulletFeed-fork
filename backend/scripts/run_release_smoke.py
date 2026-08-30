"""In-process release smoke: fresh DB, migrate, heartbeat, feed, reopen."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.evaluation.release_smoke import run_release_smoke


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("data/release-smoke.db"))
    args = parser.parse_args(argv)
    report = run_release_smoke(args.database)
    print(json.dumps(report, indent=2, sort_keys=True))
    failed = [
        name
        for name, code in report.items()
        if name in {"health", "ready", "session", "feed"} and isinstance(code, int) and code >= 400
    ]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
