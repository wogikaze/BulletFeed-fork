"""Aggregate GET /me/feed-sessions/metrics snapshots for a field diary.

Does not read Gold or blind labels. Does not set completion_gate_pass.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REPORT_VERSION = "field-session-metrics-aggregate-v1"


def _as_int(value: Any) -> int:
    if value is None:
        return 0
    return int(value)


def _as_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def normalize_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("metrics payload must be an object")
    return {
        "version": payload.get("version") or payload.get("policyVersion"),
        "session_count": _as_int(payload.get("session_count", payload.get("sessionCount"))),
        "displayed_count": _as_int(payload.get("displayed_count", payload.get("displayedCount"))),
        "useful_card_rate": _as_optional_float(
            payload.get("useful_card_rate", payload.get("usefulCardRate"))
        ),
        "already_known_reshow_rate": _as_optional_float(
            payload.get("already_known_reshow_rate", payload.get("alreadyKnownReshowRate"))
        ),
        "cards_to_useful_item": _as_optional_float(
            payload.get("cards_to_useful_item", payload.get("cardsToUsefulItem"))
        ),
        "feedback_response_rate": _as_optional_float(
            payload.get("feedback_response_rate", payload.get("feedbackResponseRate"))
        ),
    }


def _weighted_rate(rows: list[dict[str, Any]], key: str) -> float | None:
    numerator = 0.0
    displayed = 0
    for row in rows:
        rate = row[key]
        count = row["displayed_count"]
        if rate is None or count <= 0:
            continue
        numerator += rate * count
        displayed += count
    if displayed == 0:
        return None
    return numerator / displayed


def aggregate_metrics(payloads: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [normalize_metrics(item) for item in payloads]
    useful_cards: list[float] = []
    for row in rows:
        if row["cards_to_useful_item"] is not None:
            useful_cards.append(row["cards_to_useful_item"])
    return {
        "report_version": REPORT_VERSION,
        "completion_gate_pass": False,
        "blind_read": False,
        "participant_snapshot_count": len(rows),
        "session_count": sum(row["session_count"] for row in rows),
        "displayed_count": sum(row["displayed_count"] for row in rows),
        "useful_card_rate": _weighted_rate(rows, "useful_card_rate"),
        "already_known_reshow_rate": _weighted_rate(rows, "already_known_reshow_rate"),
        "cards_to_useful_item": (sum(useful_cards) / len(useful_cards)) if useful_cards else None,
        "feedback_response_rate": _weighted_rate(rows, "feedback_response_rate"),
        "source_of_truth": "GET /v1/me/feed-sessions/metrics",
        "note": (
            "Diary aggregate only. Does not complete #327 or M7. "
            "Do not treat this file as Human Gold."
        ),
    }


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain an object")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "inputs",
        nargs="+",
        type=Path,
        help="Saved GET /v1/me/feed-sessions/metrics JSON files",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = aggregate_metrics([_load_json(path) for path in args.inputs])
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
