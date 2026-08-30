"""Meaningful viewport display policy (Known-03 / viewport-exposure-v2).

A card that merely intersects the viewport is not knowledge evidence.
KIND_DISPLAYED is recorded only when this policy passes.

v1 treated omitted dwell_ms+visible_ratio as displayed for old clients.
Current Android always sends both metrics. v2 ends that window: missing
or partial metrics stay delivered. detail_opened remains an explicit
action and still counts as meaningful.

This module does not implement follow baseline (#52) and does not hide
uncertain knownness.
"""

from typing import Final

POLICY_VERSION: Final = "viewport-exposure-v2"
MIN_DWELL_MS: Final = 1000
MIN_VISIBLE_RATIO: Final = 0.50
CLIENT_CAPABILITY: Final = "android-sends-dwell-and-visible-ratio"


def is_meaningful_display(
    *,
    dwell_ms: int | None = None,
    visible_ratio: float | None = None,
    detail_opened: bool = False,
) -> bool:
    """Return True when an exposure may become KIND_DISPLAYED.

    Missing or partial metrics stay delivered. Provided metrics must
    each meet the v2 threshold. detail_opened is an explicit action.
    """
    if detail_opened:
        return True
    if dwell_ms is None or visible_ratio is None:
        return False
    if dwell_ms < MIN_DWELL_MS:
        return False
    if visible_ratio < MIN_VISIBLE_RATIO:
        return False
    return True
