from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "backend" / "app"
BLIND_INDEX = ROOT / "backend" / "tests" / "gold" / "v02" / "blind" / "index.json"


def main() -> None:
    blind = json.loads(BLIND_INDEX.read_text(encoding="utf-8"))
    forbidden = {
        "tests/gold/v02/blind",
        "gold/v02/blind",
        *(bundle_id for bundle_id in blind["bundle_ids"]),
    }
    violations: list[str] = []
    for path in APP.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        hits = sorted(token for token in forbidden if token in text)
        if hits:
            violations.append(f"{path.relative_to(ROOT)}: {', '.join(hits)}")
    if violations:
        raise SystemExit("blind Gold leakage into production code:\n" + "\n".join(violations))
    print(f"blind Gold isolation OK: {len(blind['bundle_ids'])} blind bundle ids")


if __name__ == "__main__":
    main()
