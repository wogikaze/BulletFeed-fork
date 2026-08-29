from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "backend" / "app"
HOLD_INDEX = ROOT / "backend" / "tests" / "gold" / "source_coverage" / "v01" / "blind" / "index.json"


def forbidden_tokens(index_path: Path = HOLD_INDEX) -> set[str]:
    index = json.loads(index_path.read_text(encoding="utf-8"))
    return {
        "tests/gold/source_coverage/v01/blind",
        "gold/source_coverage/v01/blind",
        *index.get("case_ids", []),
    }


def main() -> None:
    forbidden = forbidden_tokens()
    violations: list[str] = []
    for path in APP.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        hits = sorted(token for token in forbidden if token in text)
        if hits:
            violations.append(f"{path.relative_to(ROOT)}: {', '.join(hits)}")
    if violations:
        raise SystemExit("source-coverage Gold leakage into production code:\n" + "\n".join(violations))
    print(f"source-coverage Gold isolation OK: {len(forbidden)} forbidden tokens scanned")


if __name__ == "__main__":
    main()
