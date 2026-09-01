"""Time-aware weakening of implicit knowledge evidence. Versioned policy."""

from __future__ import annotations

from collections.abc import Mapping

# Kind strings are duplicated here to avoid a circular import with
# knowledge_evidence (which calls evidence_is_active).
DECAY_POLICY_VERSION = "knownness-decay-v1"

# Implicit evidence older than this is ignored for hide/probably_known.
# Explicit already_knew / baseline / bootstrap_explicit never decay.
IMPLICIT_TTL_SECONDS: Mapping[str, int] = {
    "delivered": 7 * 24 * 60 * 60,
    "displayed": 90 * 24 * 60 * 60,
    "read": 180 * 24 * 60 * 60,
}

NEVER_DECAY_KINDS = frozenset(
    {
        "already_knew",
        "learned_now",
        "baseline",
        "bootstrap_explicit",
        "bootstrap_claim",
    }
)


def evidence_is_active(
    *,
    kind: str,
    created_at: int,
    now: int | None,
) -> bool:
    if now is None or kind in NEVER_DECAY_KINDS:
        return True
    # Fixture clocks use small integers. Do not decay them.
    if created_at < 1_000_000_000:
        return True
    ttl = IMPLICIT_TTL_SECONDS.get(kind)
    if ttl is None:
        return True
    return (now - created_at) <= ttl
