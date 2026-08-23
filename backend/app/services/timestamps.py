from __future__ import annotations

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime


def canonical_timestamp(value: object) -> str | None:
    """Normalize supported source timestamps to second-precision UTC RFC3339.

    GitHub, Statuspage and JSON Feed use ISO-8601/RFC3339 while RSS/Atom commonly
    uses RFC 2822 dates. Returning one fixed-width UTC representation makes the
    ledger's TEXT ordering chronological rather than representation-dependent.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    parsed: datetime | None = None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(raw)
        except (TypeError, ValueError, OverflowError):
            return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
