from __future__ import annotations

import time
from collections.abc import Iterable

from app.config import Settings
from app.database import Database
from app.services.source_registry import canonicalize_url
from app.services.url_safety import validate_url_shape

GRANTED_SOURCE_TYPES = frozenset({"rss_atom", "json_feed", "generic_web"})

_SCHEMA = """
CREATE TABLE IF NOT EXISTS user_source_discovery_grants (
    user_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_key TEXT NOT NULL,
    granted_at INTEGER NOT NULL,
    PRIMARY KEY(user_id, source_type, source_key)
);
CREATE INDEX IF NOT EXISTS idx_user_source_discovery_grants_source
ON user_source_discovery_grants(source_type, source_key, user_id);
"""


def _ensure_schema(database: Database) -> None:
    with database.connect() as connection:
        connection.executescript(_SCHEMA)


def record_user_source_discovery_grants(
    database: Database,
    *,
    user_id: str,
    sources: Iterable[tuple[str, str]],
    now: int | None = None,
) -> None:
    """Persist only candidates the authenticated user actually discovered."""
    rows: list[tuple[str, str]] = []
    for source_type, url in sources:
        if source_type not in GRANTED_SOURCE_TYPES:
            continue
        try:
            canonical = canonicalize_url(url)
        except ValueError:
            continue
        rows.append((source_type, canonical))
    if not rows:
        return
    _ensure_schema(database)
    granted_at = int(time.time()) if now is None else now
    with database.connect() as connection:
        connection.executemany(
            """
            INSERT INTO user_source_discovery_grants (
                user_id, source_type, source_key, granted_at
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, source_type, source_key) DO UPDATE SET
                granted_at = excluded.granted_at
            """,
            [(user_id, source_type, source_key, granted_at) for source_type, source_key in rows],
        )


def user_has_source_discovery_grant(
    database: Database,
    *,
    user_id: str,
    source_type: str,
    url: str,
) -> bool:
    if source_type not in GRANTED_SOURCE_TYPES:
        return False
    try:
        source_key = canonicalize_url(url)
    except ValueError:
        return False
    _ensure_schema(database)
    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT 1
            FROM user_source_discovery_grants
            WHERE user_id = ? AND source_type = ? AND source_key = ?
            LIMIT 1
            """,
            (user_id, source_type, source_key),
        ).fetchone()
    return row is not None


def active_subscription_has_discovery_grant(
    database: Database,
    *,
    source_type: str,
    source_key: str,
) -> bool:
    """Require an active subscriber to own the grant used by the worker."""
    if source_type not in GRANTED_SOURCE_TYPES:
        return False
    try:
        canonical = canonicalize_url(source_key)
    except ValueError:
        return False
    _ensure_schema(database)
    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT 1
            FROM user_source_discovery_grants AS grants
            JOIN source_sync_subscription_users AS users
              ON users.user_id = grants.user_id
             AND users.source_type = grants.source_type
             AND users.source_key = grants.source_key
            JOIN source_sync_subscriptions AS subscriptions
              ON subscriptions.source_type = users.source_type
             AND subscriptions.source_key = users.source_key
            WHERE grants.source_type = ?
              AND grants.source_key = ?
              AND subscriptions.selected = 1
            LIMIT 1
            """,
            (source_type, canonical),
        ).fetchone()
    return row is not None


def settings_for_site_discovery(settings: Settings, url: str) -> Settings:
    """Admit only the submitted public hostname; acquisition still performs DNS/peer checks."""
    host = _public_hostname(url)
    return settings.model_copy(
        update={
            "rss_allowed_hosts": _merge_host(settings.rss_allowed_hosts, host),
            "web_allowed_hosts": _merge_host(settings.web_allowed_hosts, host),
        }
    )


def settings_for_user_subscription(
    database: Database,
    settings: Settings,
    *,
    user_id: str,
    source_type: str,
    url: str | None,
) -> Settings:
    if not url or not user_has_source_discovery_grant(
        database,
        user_id=user_id,
        source_type=source_type,
        url=url,
    ):
        return settings
    return _settings_with_source_host(settings, source_type=source_type, url=url)


def settings_for_active_source(
    database: Database,
    settings: Settings,
    *,
    source_type: str,
    source_key: str,
) -> Settings:
    if not active_subscription_has_discovery_grant(
        database,
        source_type=source_type,
        source_key=source_key,
    ):
        return settings
    return _settings_with_source_host(settings, source_type=source_type, url=source_key)


def _settings_with_source_host(settings: Settings, *, source_type: str, url: str) -> Settings:
    host = _public_hostname(url)
    updates: dict[str, str] = {}
    if source_type in {"rss_atom", "json_feed"}:
        updates["rss_allowed_hosts"] = _merge_host(settings.rss_allowed_hosts, host)
        # RSS article enrichment fetches the publisher page through the web safety path.
        updates["web_allowed_hosts"] = _merge_host(settings.web_allowed_hosts, host)
    elif source_type == "generic_web":
        updates["web_allowed_hosts"] = _merge_host(settings.web_allowed_hosts, host)
    return settings.model_copy(update=updates) if updates else settings


def _public_hostname(url: str) -> str:
    parsed = validate_url_shape(url.strip(), source_name="Source")
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        raise ValueError("source URL has no hostname")
    return host


def _merge_host(raw_hosts: str, host: str) -> str:
    hosts = {item.strip().lower().rstrip(".") for item in raw_hosts.split(",") if item.strip()}
    hosts.add(host)
    return ",".join(sorted(hosts))
