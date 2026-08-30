"""Build metadata-grounded AI-silver judgments for pilot and dev only.

These labels are evaluation data, never Human Gold, and never read by
production scoring. The rubric is intentionally conservative: ambiguous
matches remain ambiguous instead of being forced into a positive label.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

CORPUS = Path(__file__).resolve().parents[1] / "tests" / "gold" / "real_world_validation" / "v01"
DATASET_VERSION = "real-world-validation-v0.2"
LABEL_PROTOCOL_VERSION = "label-protocol-v1"
PROVENANCE = (
    "AI-silver; annotator=gpt-5.6-luna; "
    "generator=metadata-rubric-v1; protocol=label-protocol-v1"
)
TARGET_PER_SPLIT = 5_000
WORD_RE = re.compile(r"[a-z0-9][a-z0-9+._-]*")


def _load(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"{path} must contain a JSON array")
    return payload


def _write(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _tokens(value: str) -> set[str]:
    return set(WORD_RE.findall(value.casefold()))


def _package_token(event: dict[str, Any], source: dict[str, Any]) -> str:
    title = str(event["title"]).split()
    if title:
        return title[0].casefold()
    return str(source["publisher"]).rsplit("/", 1)[-1].casefold()


def _label(
    profile: dict[str, Any],
    event: dict[str, Any],
    source: dict[str, Any],
) -> dict[str, Any]:
    profile_tokens = set().union(*(_tokens(str(item)) for item in profile["explicit_interests"]))
    source_tokens = _tokens(f"{source['publisher']} {source['canonical_url']}")
    event_tokens = _tokens(str(event["title"]))
    direct = bool(profile_tokens & (event_tokens | source_tokens))
    known_before = event["event_id"] in set(profile["known_before_event_ids"])
    package = _package_token(event, source)
    registry = str(source["publisher"]).split(" ", 1)[0].casefold()
    ecosystem_matches = {
        "npm": {"javascript", "typescript", "node.js", "react"},
        "pypi": {"python", "django", "fastapi", "pandas", "numpy"},
        "crates": {"rust", "wasm", "webassembly"},
    }
    adjacent = bool(profile_tokens & ecosystem_matches.get(registry, set()))
    common_interest = profile_tokens & {"go", "ai", "sql", "url", "time"}
    lexical_trap = bool(common_interest & event_tokens) and package not in profile_tokens
    if known_before:
        stratum = "already_known"
        relevance = 3 if direct else 1
        importance = 2 if direct else 0
        should_surface = False
        ambiguous = False
        rationale = "The constructed history-rich profile marks this event as known before evaluation."
    elif direct:
        stratum = "clear_positive"
        relevance = 3
        importance = 3 if profile["security_sensitivity"] == "high" else 2
        should_surface = True
        ambiguous = False
        rationale = "Event title directly matches an explicit constructed profile interest."
    elif adjacent:
        stratum = "semantic_adjacent"
        relevance = 2
        importance = 2 if profile["security_sensitivity"] == "high" else 1
        should_surface = True
        ambiguous = False
        rationale = "The authoritative package registry matches the profile's declared ecosystem."
    elif lexical_trap:
        stratum = "lexical_trap"
        relevance = 0
        importance = 0
        should_surface = False
        ambiguous = True
        rationale = "A short token overlaps lexically, but the package identity is not an explicit interest."
    else:
        stratum = "unrelated"
        relevance = 0
        importance = 0
        should_surface = False
        ambiguous = False
        rationale = "No explicit interest token occurs in the concrete event title."
    return {
        "stratum": stratum,
        "relevance": relevance,
        "importance_to_user": importance,
        "known_before": known_before,
        "should_surface": should_surface,
        "rationale": rationale,
        "ambiguous": ambiguous,
    }


def _candidate_rows(split: str) -> list[dict[str, Any]]:
    profiles = _load(CORPUS / split / "profiles.json")
    events = [event for event in _load(CORPUS / split / "events.json") if event["is_real_event"]]
    sources = {
        source["event_id"]: source
        for source in _load(CORPUS / split / "sources.json")
        if source["event_id"]
    }
    rows: list[dict[str, Any]] = []
    for profile in profiles:
        for event in events:
            source = sources[event["event_id"]]
            identity = f"{split}|{profile['profile_id']}|{event['event_id']}"
            digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
            label = _label(profile, event, source)
            rows.append(
                {
                    "judgment_id": f"jdg_m2_{split[0]}_{digest[:16]}",
                    "profile_id": profile["profile_id"],
                    "event_id": event["event_id"],
                    "split": split,
                    **label,
                    "provenance": PROVENANCE,
                    "label_protocol_version": LABEL_PROTOCOL_VERSION,
                    "dataset_version": DATASET_VERSION,
                    "_sort": digest,
                }
            )
    rows.sort(key=lambda row: row["_sort"])
    for row in rows:
        row.pop("_sort", None)
    return rows


def _append_judgments(split: str, rows: list[dict[str, Any]]) -> int:
    path = CORPUS / split / "judgments.json"
    existing = [
        row
        for row in _load(path)
        if not str(row["judgment_id"]).startswith("jdg_m2_")
    ]
    existing_ids = {row["judgment_id"] for row in existing}
    available = [row for row in rows if row["judgment_id"] not in existing_ids]
    priority = {
        "clear_positive": 0,
        "semantic_adjacent": 1,
        "already_known": 2,
        "lexical_trap": 3,
        "hard_negative": 4,
        "new_detail": 5,
        "cross_source_duplicate": 6,
        "correction_conflict": 7,
        "unrelated": 8,
    }
    available.sort(key=lambda row: (priority[row["stratum"]], row["judgment_id"]))
    selected = available[:TARGET_PER_SPLIT]
    _write(path, [*existing, *selected])
    index_path = CORPUS / split / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["judgment_ids"] = [row["judgment_id"] for row in [*existing, *selected]]
    _write(index_path, index)
    return len(selected)


def main() -> None:
    selected: dict[str, int] = {}
    strata: Counter[str] = Counter()
    for split in ("pilot", "dev"):
        rows = _candidate_rows(split)
        selected[split] = _append_judgments(split, rows)
        selected_rows = [
            row
            for row in _load(CORPUS / split / "judgments.json")
            if str(row["provenance"]).startswith("AI-silver")
        ]
        strata.update(row["stratum"] for row in selected_rows)
    report = {
        "generator_version": "m2-ai-silver-metadata-rubric-v1",
        "label_source": "AI-silver",
        "human_gold": False,
        "blind_read": False,
        "protocol_version": LABEL_PROTOCOL_VERSION,
        "dataset_version": DATASET_VERSION,
        "selected_by_split": selected,
        "selected_total": sum(selected.values()),
        "strata": dict(sorted(strata.items())),
        "independent_agreement": "not_collected",
    }
    _write(CORPUS / "ai_silver_report.json", report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
