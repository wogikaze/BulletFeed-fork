"""Collect topic-only source discovery candidates from external GitHub metadata."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEFAULT_TOPICS = ROOT / "tests" / "fixtures" / "source_discovery" / "quality_topics.json"
DEFAULT_OUTPUT = ROOT / "tests" / "fixtures" / "source_discovery" / "independent_candidates.json"


def _load_topics(path: Path):
    from app.evaluation.source_discovery_github_collector import (
        SourceDiscoveryTopicInput,
        validate_topic_input,
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    value = SourceDiscoveryTopicInput.model_validate(payload)
    validate_topic_input(value)
    return value


async def _run(args: argparse.Namespace) -> int:
    from app.config import Settings
    from app.evaluation.source_discovery_github_collector import (
        collect_github_independent_candidates,
    )

    topics = _load_topics(args.topics)
    token = os.environ.get("GITHUB_TOKEN") or None
    artifact = await collect_github_independent_candidates(
        Settings(),
        topics,
        token=token,
        repositories_per_topic=args.repositories_per_topic,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(artifact.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "collector_version": artifact.collector_version,
                "topic_count": len(topics.topics),
                "candidate_count": len(artifact.items),
                "gold_read": artifact.gold_read,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topics", type=Path, default=DEFAULT_TOPICS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--repositories-per-topic", type=int, default=3, choices=range(1, 6))
    args = parser.parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except (OSError, ValueError, ValidationError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
