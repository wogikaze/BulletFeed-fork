"""Meaningful viewport display policy (Known-03 / viewport-exposure-v1).

A card that merely intersects the viewport is not knowledge evidence.
KIND_DISPLAYED is recorded only when this policy passes.

Compatibility: if a client omits both dwell_ms and visible_ratio, the
exposure is treated as displayed so existing clients keep working.
New clients send dwell_ms + visible_ratio. The backend still enforces
the thresholds so a brief or tiny visibility cannot become displayed.

detail_opened is an explicit user action (open Event detail) and counts
as meaningful even when dwell/ratio are below threshold.

This module does not implement follow baseline (#52) and does not hide
uncertain knownness.
"""

from typing import Final

POLICY_VERSION: Final = "viewport-exposure-v1"
MIN_DWELL_MS: Final = 1000
MIN_VISIBLE_RATIO: Final = 0.50


def is_meaningful_display(
    *,
    dwell_ms: int | None = None,
    visible_ratio: float | None = None,
    detail_opened: bool = False,
) -> bool:
    """Return True when an exposure may become KIND_DISPLAYED.

    Missing metrics → displayed (backward compatible).
    Provided metrics must each meet the v1 threshold.
    """
    if detail_opened:
        return True
    if dwell_ms is None and visible_ratio is None:
        return True
    if dwell_ms is not None and dwell_ms < MIN_DWELL_MS:
        return False
    if visible_ratio is not None and visible_ratio < MIN_VISIBLE_RATIO:
        return False
    return True
