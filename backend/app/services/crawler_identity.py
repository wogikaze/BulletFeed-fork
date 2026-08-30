"""Configurable crawler identity for public fetches.

Robots evaluation and the subsequent HTTP fetch must use the same User-Agent.
"""

from __future__ import annotations

import re

RELEASE_CRAWLER_USER_AGENT = (
    "BulletFeed/1.0 (+https://github.com/wogikaze/BulletFeed-fork; source-watch)"
)
_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]*(/[0-9A-Za-z._\-]+)?")


def validate_crawler_user_agent(value: str) -> str:
    cleaned = str(value).strip()
    if not cleaned:
        raise ValueError("crawler user-agent is required")
    if any(ord(char) < 32 for char in cleaned):
        raise ValueError("crawler user-agent contains control characters")
    if len(cleaned) > 256:
        raise ValueError("crawler user-agent exceeds 256 characters")
    if not _TOKEN.match(cleaned):
        raise ValueError("crawler user-agent must start with a product token")
    return cleaned
