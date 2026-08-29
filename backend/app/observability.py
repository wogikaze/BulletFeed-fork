from __future__ import annotations

import hashlib
import json
import logging
import re
from collections import Counter, deque
from typing import Any

LOGGER = logging.getLogger("bulletfeed.pipeline")

_BLOCKED_KEYS = frozenset(
    {
        "authorization",
        "access_token",
        "app_access_token",
        "api_key",
        "client_secret",
        "code_verifier",
        "github_token",
        "github_token_encrypted",
        "id_token",
        "lease_token",
        "password",
        "poll_token",
        "refresh_token",
        "secret",
        "source_key",
        "token",
        "token_encryption_key",
        "verifier",
    }
)

_SECRET_PREFIXES = (
    "ghp_",
    "gho_",
    "ghu_",
    "ghs_",
    "ghr_",
    "github_pat_",
)

_SECRET_VALUES = frozenset(
    {
        "client-secret",
        "client_secret",
    }
)

_PREFIX_PATTERN = re.compile(
    r"(?:ghp_|gho_|ghu_|ghs_|ghr_|github_pat_)[A-Za-z0-9_]+",
    re.IGNORECASE,
)
_BEARER_PATTERN = re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-+=/]+")

_MAX_RECORDS = 1000
_records: deque[dict[str, Any]] = deque(maxlen=_MAX_RECORDS)
_counters: Counter[str] = Counter()


def source_key_digest(source_type: str, source_key: str) -> str:
    raw = f"{source_type}|{source_key}".encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def sanitize(value: Any, *, key: str | None = None) -> Any:
    if key is not None and key.casefold() in _BLOCKED_KEYS:
        return None
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for item_key, item in value.items():
            if str(item_key).casefold() in _BLOCKED_KEYS:
                continue
            cleaned[str(item_key)] = sanitize(item, key=str(item_key))
        return cleaned
    if isinstance(value, (list, tuple)):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        return _sanitize_text(value)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _sanitize_text(str(value))


def _sanitize_text(value: str) -> str:
    if value.casefold() in _SECRET_VALUES:
        return "[redacted]"
    lowered = value.casefold()
    if any(lowered.startswith(prefix) for prefix in _SECRET_PREFIXES):
        return "[redacted]"
    redacted = _PREFIX_PATTERN.sub("[redacted]", value)
    redacted = _BEARER_PATTERN.sub("Bearer [redacted]", redacted)
    return redacted


def record(event: str, **fields: Any) -> dict[str, Any]:
    payload = {"event": event, **sanitize(fields)}
    serialized = json.dumps(payload, sort_keys=True, default=str)
    serialized = _sanitize_text(serialized)
    payload = json.loads(serialized)
    _records.append(payload)
    _counters[event] += 1
    LOGGER.info("%s", serialized)
    return payload


def snapshot() -> tuple[dict[str, Any], ...]:
    return tuple(_records)


def counters() -> dict[str, int]:
    return dict(_counters)


def reset() -> None:
    _records.clear()
    _counters.clear()


def public_counters() -> dict[str, int]:
    return {
        "fetch": _counters.get("fetch", 0),
        "observation": _counters.get("observation", 0),
        "revision": _counters.get("revision", 0),
        "projection": _counters.get("projection", 0),
        "syncFailure": _counters.get("sync_failure", 0),
    }
