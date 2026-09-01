"""Read versioned measurement artifacts. Hard Gate does not invent unmeasured PASS."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

MEASUREMENT_NAMES = ("g1", "g2", "g3", "g4", "g5")


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must be a JSON object")
    return payload


def load_freeze(gold_dir: Path) -> dict[str, Any]:
    freeze = load_json(gold_dir / "g0_freeze.json")
    if freeze is None:
        raise FileNotFoundError(gold_dir / "g0_freeze.json")
    return freeze


def measurement_path(gold_dir: Path, name: str) -> Path:
    return gold_dir / "measurements" / f"{name}_measurement.json"


def load_measurement(gold_dir: Path, name: str) -> dict[str, Any] | None:
    return load_json(measurement_path(gold_dir, name))


def metric_meets_floor(value: object, floor: float, *, higher_is_better: bool = True) -> bool:
    if value is None:
        return False
    number = float(value)
    return number >= floor if higher_is_better else number <= floor


def compare_metrics(metrics: dict[str, Any], floors: dict[str, float], required: dict[str, str]) -> list[str]:
    """required maps freeze key -> measurement metric key."""
    failures: list[str] = []
    for floor_key, metric_key in required.items():
        if floor_key not in floors:
            continue
        higher = not floor_key.endswith("_rate") or "duplicate" not in floor_key
        if floor_key in {"g3_duplicate_item_rate", "g4_boilerplate_fp", "g4_article_split"}:
            higher = False
        if not metric_meets_floor(metrics.get(metric_key), floors[floor_key], higher_is_better=higher):
            failures.append(floor_key)
    return failures
