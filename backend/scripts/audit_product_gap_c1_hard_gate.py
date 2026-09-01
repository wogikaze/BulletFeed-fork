"""Emit the honest #328 challenge-1 Hard Completion Gate audit."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.evaluation.product_gap_c1_hard_gate import evaluate_c1_hard_gate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    report = evaluate_c1_hard_gate()
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if args.check and not report["completion_gate_pass"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
