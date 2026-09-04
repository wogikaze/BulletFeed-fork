"""Write the deterministic source-discovery quality measurement artifact."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEFAULT_CORPUS = ROOT / "tests" / "gold" / "source_discovery" / "v02" / "corpus.json"
DEFAULT_OUTPUT = (
    ROOT / "tests" / "gold" / "source_discovery" / "v02" / "current_main_measurement.json"
)


def _repository_sha() -> str | None:
    env_sha = os.environ.get("GITHUB_SHA")
    if env_sha:
        return env_sha
    git = shutil.which("git")
    if git is None:
        return None
    try:
        completed = subprocess.run(  # noqa: S603
            [git, "rev-parse", "HEAD"],
            cwd=ROOT.parent,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    return completed.stdout.strip() or None


def main(argv: list[str] | None = None) -> int:
    from app.evaluation.source_discovery_quality import (
        evaluate_source_discovery_quality,
        load_source_discovery_quality_corpus,
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--independent-candidates",
        type=Path,
        default=None,
        help=(
            "Recorded external candidate artifact. When omitted, builtin and curated hints "
            "remain disabled and the benchmark stays fail-closed if no candidates exist."
        ),
    )
    args = parser.parse_args(argv)

    corpus = load_source_discovery_quality_corpus(args.corpus)
    source_sha = _repository_sha()
    if args.independent_candidates is None:
        report = evaluate_source_discovery_quality(corpus, source_sha=source_sha)
    else:
        from app.evaluation.source_discovery_independent import (
            evaluate_source_discovery_quality_with_independent_candidates,
            load_independent_candidate_artifact,
        )

        candidates = load_independent_candidate_artifact(args.independent_candidates)
        report = evaluate_source_discovery_quality_with_independent_candidates(
            corpus,
            candidates,
            source_sha=source_sha,
        )
    payload = report.as_dict()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "passed": payload["passed"],
                "evaluation_status": payload["evaluation_status"],
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
