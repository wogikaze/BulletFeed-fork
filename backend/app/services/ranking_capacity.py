"""Display-frame capacity policy, versioned separately from ranking weights.

Candidate scoring stays on RANKING_POLICY_VERSION. This module only chooses
which already-scored items occupy the short display frame. Items are reordered,
never dropped or hard-hidden. Correction/security priority is preserved.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

CAPACITY_POLICY_VERSION = "capacity-policy-v1"
CAPACITY_OFF = "off"
CAPACITY_TOPIC_CAP = "capacity-topic-cap-v1"
CAPACITY_RESERVED = "capacity-reserved-v1"
CAPACITY_SOURCE_CAP = "capacity-source-cap-v1"
DISPLAY_FRAME_K = 10
MAX_PER_TOPIC = 1
MAX_PER_SOURCE = 6
RESERVED_DIRECT_SLOTS = 2
RESERVED_KIND_SLOTS: Mapping[str, int] = {
    "incident": 1,
    "security": 1,
}
_RELATED_LEVELS = frozenset({"direct", "adjacent"})
_SECURITY_SOURCES = frozenset({"osv", "github_advisory"})
_INCIDENT_SOURCES = frozenset({"statuspage"})
_INCIDENT_DELTAS = frozenset({"state_update"})
_HARD_PRIORITY_TIER = 3


@dataclass(frozen=True)
class CapacitySpec:
    version: str
    display_k: int = DISPLAY_FRAME_K
    max_per_topic: int | None = None
    max_per_source: int | None = None
    reserved_direct: int = 0
    reserved_kinds: Mapping[str, int] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.reserved_kinds is None:
            object.__setattr__(self, "reserved_kinds", {})


PRODUCTION_SPEC = CapacitySpec(
    version=CAPACITY_POLICY_VERSION,
    display_k=DISPLAY_FRAME_K,
    max_per_topic=MAX_PER_TOPIC,
    reserved_direct=RESERVED_DIRECT_SLOTS,
    reserved_kinds=RESERVED_KIND_SLOTS,
)
TOPIC_CAP_SPEC = CapacitySpec(
    version=CAPACITY_TOPIC_CAP,
    display_k=DISPLAY_FRAME_K,
    max_per_topic=MAX_PER_TOPIC,
)
RESERVED_SPEC = CapacitySpec(
    version=CAPACITY_RESERVED,
    display_k=DISPLAY_FRAME_K,
    reserved_direct=RESERVED_DIRECT_SLOTS,
    reserved_kinds=RESERVED_KIND_SLOTS,
)
SOURCE_CAP_SPEC = CapacitySpec(
    version=CAPACITY_SOURCE_CAP,
    display_k=DISPLAY_FRAME_K,
    max_per_source=MAX_PER_SOURCE,
)

_SPECS: Mapping[str, CapacitySpec] = {
    CAPACITY_POLICY_VERSION: PRODUCTION_SPEC,
    CAPACITY_TOPIC_CAP: TOPIC_CAP_SPEC,
    CAPACITY_RESERVED: RESERVED_SPEC,
    CAPACITY_SOURCE_CAP: SOURCE_CAP_SPEC,
}


def capacity_spec(version: str) -> CapacitySpec:
    if version in {CAPACITY_OFF, "", "none"}:
        raise ValueError("capacity policy is off")
    spec = _SPECS.get(version)
    if spec is None:
        raise ValueError(f"unknown capacity policy {version}")
    return spec


def occupancy_kind(candidate: Any) -> str:
    source = (getattr(candidate, "source_type", "") or "").strip().casefold()
    delta = (getattr(candidate, "delta_type", "") or "").strip().casefold()
    if source in _SECURITY_SOURCES:
        return "security"
    if source in _INCIDENT_SOURCES or delta in _INCIDENT_DELTAS:
        return "incident"
    if delta in {"correction", "unresolved_contradiction", "unresolved_conflict"}:
        return "correction"
    return "release"


def apply_capacity_policy(
    ranked: Sequence[Any],
    candidates: Mapping[str, Any],
    *,
    policy_version: str = CAPACITY_POLICY_VERSION,
    display_k: int | None = None,
) -> list[Any]:
    """Reorder a fully ranked list so the display frame is capacity-aware.

    The candidate set remains every ranked item. The first ``display_k``
    positions are the display frame. Later positions keep original relative
    order. Hidden flags and item membership are unchanged.
    """
    if policy_version in {CAPACITY_OFF, "", "none"}:
        return [_stamp(item, CAPACITY_OFF) for item in ranked]
    spec = capacity_spec(policy_version)
    frame_k = display_k if display_k is not None else spec.display_k
    ranked_list = list(ranked)
    if frame_k < 1 or len(ranked_list) <= 1:
        return [_stamp(item, spec.version) for item in ranked_list]

    remaining = list(ranked_list)
    selected: list[Any] = []
    while remaining and len(selected) < frame_k:
        hold_for_reserved = _must_hold_for_reserved(
            remaining, selected, candidates, spec, frame_k=frame_k
        )
        index = _first_eligible(
            remaining, selected, candidates, spec, reserved_only=hold_for_reserved
        )
        if index is None:
            index = 0
        selected.append(remaining.pop(index))
    remainder = remaining
    return [_stamp(item, spec.version) for item in [*selected, *remainder]]


def _must_hold_for_reserved(
    remaining: Sequence[Any],
    selected: Sequence[Any],
    candidates: Mapping[str, Any],
    spec: CapacitySpec,
    *,
    frame_k: int,
) -> bool:
    unmet = _unmet_reserved_available(remaining, selected, candidates, spec)
    return frame_k - len(selected) <= unmet


def _unmet_reserved_available(
    remaining: Sequence[Any],
    selected: Sequence[Any],
    candidates: Mapping[str, Any],
    spec: CapacitySpec,
) -> int:
    unmet = 0
    if spec.reserved_direct:
        need = spec.reserved_direct - _count_direct(selected, candidates)
        available = sum(
            1 for item in remaining if _relation_level(candidates.get(item.item_id, item)) == "direct"
        )
        unmet += min(max(need, 0), available)
    for kind, quota in spec.reserved_kinds.items():
        need = quota - _count_kind(selected, candidates, kind)
        available = sum(
            1
            for item in remaining
            if occupancy_kind(candidates.get(item.item_id, item)) == kind
            and _relation_level(candidates.get(item.item_id, item)) in _RELATED_LEVELS
        )
        unmet += min(max(need, 0), available)
    return unmet


def _first_eligible(
    remaining: Sequence[Any],
    selected: Sequence[Any],
    candidates: Mapping[str, Any],
    spec: CapacitySpec,
    *,
    reserved_only: bool,
) -> int | None:
    for index, item in enumerate(remaining):
        if _is_eligible(item, selected, candidates, spec, reserved_only=reserved_only):
            return index
    return None


def _fills_reserved(
    item: Any,
    selected: Sequence[Any],
    candidates: Mapping[str, Any],
    spec: CapacitySpec,
) -> bool:
    if getattr(item, "priority_tier", 1) >= _HARD_PRIORITY_TIER:
        return True
    candidate = candidates.get(item.item_id)
    if candidate is None:
        return False
    if spec.reserved_direct and _relation_level(candidate) == "direct":
        if _count_direct(selected, candidates) < spec.reserved_direct:
            return True
    kind = occupancy_kind(candidate)
    quota = spec.reserved_kinds.get(kind, 0)
    if quota and _count_kind(selected, candidates, kind) < quota:
        return _relation_level(candidate) in _RELATED_LEVELS
    return False


def _is_eligible(
    item: Any,
    selected: Sequence[Any],
    candidates: Mapping[str, Any],
    spec: CapacitySpec,
    *,
    reserved_only: bool,
) -> bool:
    if _fills_reserved(item, selected, candidates, spec):
        return True
    if reserved_only:
        return False
    candidate = candidates.get(item.item_id)
    if candidate is None:
        return True
    if spec.max_per_topic is not None:
        topic = _topic_key(candidate)
        if topic and _count_topic(selected, candidates, topic) >= spec.max_per_topic:
            return False
    if spec.max_per_source is not None:
        source = _source_type(candidate)
        if source and _count_source(selected, candidates, source) >= spec.max_per_source:
            return False
    return True


def _topic_key(candidate: Any) -> str:
    return (getattr(candidate, "topic_key", "") or "").strip()


def _source_type(candidate: Any) -> str:
    return (getattr(candidate, "source_type", "") or "").strip().casefold()


def _relation_level(candidate: Any) -> str:
    return (getattr(candidate, "relation_level", "") or "").strip().casefold()


def _count_topic(selected: Sequence[Any], candidates: Mapping[str, Any], topic: str) -> int:
    return sum(1 for item in selected if _topic_key(candidates.get(item.item_id, item)) == topic)


def _count_source(selected: Sequence[Any], candidates: Mapping[str, Any], source: str) -> int:
    return sum(1 for item in selected if _source_type(candidates.get(item.item_id, item)) == source)


def _count_direct(selected: Sequence[Any], candidates: Mapping[str, Any]) -> int:
    return sum(1 for item in selected if _relation_level(candidates.get(item.item_id, item)) == "direct")


def _count_kind(selected: Sequence[Any], candidates: Mapping[str, Any], kind: str) -> int:
    return sum(1 for item in selected if occupancy_kind(candidates.get(item.item_id, item)) == kind)


def _stamp(item: Any, version: str) -> Any:
    if hasattr(item, "capacity_policy_version"):
        return replace(item, capacity_policy_version=version)
    return item
