"""Write the deterministic source-discovery quality measurement artifact."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEFAULT_CORPUS = ROOT / "tests" / "gold" / "source_discovery" / "v02" / "corpus.json"
DEFAULT_OUTPUT = (
    ROOT / "tests" / "gold" / "source_discovery" / "v02" / "current_main_measurement.json"
)


def main(argv: list[str] | None = None) -> int:
    from app.evaluation.source_discovery_quality import (
        evaluate_source_discovery_quality,
        load_source_discovery_quality_corpus,
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    corpus = load_source_discovery_quality_corpus(args.corpus)
    report = evaluate_source_discovery_quality(corpus)
    payload = report.as_dict()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "passed": payload["passed"],
                "metrics": payload["metrics"],
                "failure_class_counts": payload["failure_class_counts"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
