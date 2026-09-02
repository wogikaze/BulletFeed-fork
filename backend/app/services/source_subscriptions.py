from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlparse

from fastapi import HTTPException, status

from app.config import Settings
from app.database import Database
from app.errors import not_found, unprocessable
from app.services.feed_projection import project_event_for_audience
from app.services.follow_baseline import SUBJECT_SOURCE, record_follow_baseline
from app.services.rss import validate_feed_url
from app.services.source_catalog import SourceKind
from app.services.source_registry import (
    AuthorityStatus,
    Endpoint,
    SourceRegistry,
    VerificationStatus,
    canonicalize_url,
    endpoint_id,
)
from app.services.statuspage import PAGE_ID_PATTERN
from app.services.web_snapshots import validate_web_url

USER_SOURCE_TYPES = frozenset({"statuspage", "rss_atom", "json_feed", "generic_web"})
_STATUSPAGE_HOST_SUFFIX = ".statuspage.io"


@dataclass(frozen=True)
class UserSourceSubscription:
    id: str
    kind: str
    canonical_url: str
    page_id: str | None
    publisher_slug: str | None
    publisher_display_name: str | None
    selected: bool
    last_success_at: int | None
    last_attempt_at: int | None
    failure_count: int
    next_run_at: int | None
    created: bool = False

    @property
    def state(self) -> str:
        if self.failure_count > 0:
            return "failing"
        if self.last_success_at is None:
            return "pending"
        return "ok"


def upsert_source_subscription(
    database: Database,
    *,
    source_type: str,
    source_key: str,
    selected: int = 1,
) -> None:
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO source_sync_subscriptions (source_type, source_key, selected)
            VALUES (?, ?, ?)
            ON CONFLICT(source_type, source_key) DO UPDATE SET selected = excluded.selected
            """,
            (source_type, source_key, selected),
        )


def add_subscription_user(
    database: Database,
    *,
    source_type: str,
    source_key: str,
    user_id: str,
) -> None:
    upsert_source_subscription(
        database,
        source_type=source_type,
        source_key=source_key,
        selected=1,
    )
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO source_sync_subscription_users (source_type, source_key, user_id)
            VALUES (?, ?, ?)
            ON CONFLICT(source_type, source_key, user_id) DO NOTHING
            """,
            (source_type, source_key, user_id),
        )


def list_subscription_user_ids(
    database: Database,
    *,
    source_type: str,
    source_keys: Sequence[str],
) -> tuple[str, ...]:
    keys = tuple(dict.fromkeys(key for key in source_keys if key))
    if not keys:
        return ()
    user_ids: list[str] = []
    with database.connect() as connection:
        for source_key in keys:
            rows = connection.execute(
                """
                SELECT users.user_id
                FROM source_sync_subscription_users AS users
                JOIN source_sync_subscriptions AS subscriptions
                  ON subscriptions.source_type = users.source_type
                 AND subscriptions.source_key = users.source_key
                WHERE users.source_type = ?
                  AND users.source_key = ?
                  AND subscriptions.selected = 1
                ORDER BY users.user_id
                """,
                (source_type, source_key),
            ).fetchall()
            user_ids.extend(row["user_id"] for row in rows)
    return tuple(sorted(dict.fromkeys(user_ids)))


def project_events_for_subscription_audience(
    database: Database,
    *,
    source_type: str,
    source_keys: Sequence[str],
    event_ids: Sequence[str],
) -> None:
    user_ids = list_subscription_user_ids(
        database,
        source_type=source_type,
        source_keys=source_keys,
    )
    for event_id in event_ids:
        project_event_for_audience(database, event_id=event_id, user_ids=user_ids)


def ensure_source_sync_job(
    database: Database,
    *,
    source_type: str,
    source_key: str,
    now: int | None = None,
) -> None:
    current = int(time.time()) if now is None else now
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO source_sync_jobs (source_type, source_key, next_run_at)
            VALUES (?, ?, ?)
            ON CONFLICT(source_type, source_key) DO NOTHING
            """,
            (source_type, source_key, current),
        )


def subscribe_official_feeds_for_followed_topic(
    database: Database,
    *,
    user_id: str,
    topic_name: str,
    now: int | None = None,
) -> int:
    """Attach curated official RSS/JSON feeds when the user follows a topic.

    This is a user-initiated follow side-effect, not discovery-as-evidence.
    URLs come from code-reviewed seeds; the sync worker still SSRF-checks fetches.
    """
    from app.services.source_discovery_seeds import SourceSeed, official_subscribe_seeds_for_topic

    seeds = official_subscribe_seeds_for_topic(topic_name)
    if not seeds:
        return 0
    wanted: list[tuple[SourceSeed, str]] = []
    for seed in seeds:
        try:
            wanted.append((seed, canonicalize_url(seed.url)))
        except ValueError:
            continue
    if not wanted:
        return 0
    with database.connect() as connection:
        existing = {
            (str(row["source_type"]), str(row["source_key"]))
            for row in connection.execute(
                """
                SELECT source_type, source_key
                FROM source_sync_subscription_users
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchall()
        }
    pending = [
        (seed, canonical)
        for seed, canonical in wanted
        if (seed.family.value, canonical) not in existing
    ]
    if not pending:
        return 0
    registry = SourceRegistry(database)
    attached = 0
    followed_at = int(time.time()) if now is None else now
    for seed, canonical in pending:
        duplicate = registry.find_duplicate_endpoint(canonical, family=seed.family)
        if duplicate is None:
            catalog = _japanese_registry_status(canonical)
            endpoint = registry.register_endpoint(
                url=canonical,
                family=seed.family,
                verification_status=catalog[0] if catalog else None,
                authority_status=catalog[1] if catalog else None,
            )
        else:
            endpoint = _align_endpoint_status(registry, duplicate, canonical)
        source_type = seed.family.value
        source_key = endpoint.canonical_url
        already = _user_has_subscription(
            database,
            user_id=user_id,
            source_type=source_type,
            source_key=source_key,
        )
        add_subscription_user(
            database,
            source_type=source_type,
            source_key=source_key,
            user_id=user_id,
        )
        if not already:
            with database.connect() as connection:
                record_follow_baseline(
                    connection,
                    user_id=user_id,
                    subject_kind=SUBJECT_SOURCE,
                    subject_id=f"{source_type}:{source_key}",
                    catch_up=False,
                    followed_at=followed_at,
                    source_type=source_type,
                    source_key=source_key,
                )
            attached += 1
        ensure_source_sync_job(
            database,
            source_type=source_type,
            source_key=source_key,
            now=now,
        )
    return attached


def ensure_official_feeds_for_user(
    database: Database,
    *,
    user_id: str,
    now: int | None = None,
) -> int:
    """Idempotently attach curated feeds for topics the user already follows."""
    with database.connect() as connection:
        names = [
            str(row["name"])
            for row in connection.execute(
                "SELECT name FROM topics WHERE user_id = ? ORDER BY sort_order ASC, created_at ASC",
                (user_id,),
            ).fetchall()
        ]
    attached = 0
    for name in names:
        attached += subscribe_official_feeds_for_followed_topic(
            database,
            user_id=user_id,
            topic_name=name,
            now=now,
        )
    return attached


def add_user_source_subscription(
    database: Database,
    settings: Settings,
    *,
    user_id: str,
    kind: str,
    url: str | None = None,
    page_id: str | None = None,
    now: int | None = None,
    registry: SourceRegistry | None = None,
    catch_up: bool = False,
    verification_status: str | None = None,
    authority_status: str | None = None,
) -> UserSourceSubscription:
    source_type, source_key, canonical_url, resolved_page_id = resolve_user_source_identity(
        settings,
        kind=kind,
        url=url,
        page_id=page_id,
        registry=registry or SourceRegistry(database),
        verification_status=verification_status,
        authority_status=authority_status,
    )
    already = _user_has_subscription(
        database,
        user_id=user_id,
        source_type=source_type,
        source_key=source_key,
    )
    add_subscription_user(
        database,
        source_type=source_type,
        source_key=source_key,
        user_id=user_id,
    )
    if not already:
        followed_at = int(time.time()) if now is None else now
        with database.connect() as connection:
            record_follow_baseline(
                connection,
                user_id=user_id,
                subject_kind=SUBJECT_SOURCE,
                subject_id=f"{source_type}:{source_key}",
                catch_up=catch_up,
                followed_at=followed_at,
                source_type=source_type,
                source_key=source_key,
            )
    ensure_source_sync_job(
        database,
        source_type=source_type,
        source_key=source_key,
        now=now,
    )
    item = _load_user_subscription(
        database,
        user_id=user_id,
        source_type=source_type,
        source_key=source_key,
        registry=registry or SourceRegistry(database),
    )
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Source subscription could not be loaded",
        )
    return UserSourceSubscription(
        id=item.id,
        kind=item.kind,
        canonical_url=canonical_url,
        page_id=resolved_page_id,
        publisher_slug=item.publisher_slug,
        publisher_display_name=item.publisher_display_name,
        selected=item.selected,
        last_success_at=item.last_success_at,
        last_attempt_at=item.last_attempt_at,
        failure_count=item.failure_count,
        next_run_at=item.next_run_at,
        created=not already,
    )


def list_user_source_subscriptions(
    database: Database,
    *,
    user_id: str,
    registry: SourceRegistry | None = None,
) -> tuple[UserSourceSubscription, ...]:
    source_registry = registry or SourceRegistry(database)
    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT users.source_type, users.source_key, subscriptions.selected,
                   jobs.last_success_at, jobs.last_attempt_at, jobs.failure_count, jobs.next_run_at
            FROM source_sync_subscription_users AS users
            JOIN source_sync_subscriptions AS subscriptions
              ON subscriptions.source_type = users.source_type
             AND subscriptions.source_key = users.source_key
            LEFT JOIN source_sync_jobs AS jobs
              ON jobs.source_type = users.source_type
             AND jobs.source_key = users.source_key
            WHERE users.user_id = ?
              AND users.source_type IN ('statuspage', 'rss_atom', 'json_feed', 'generic_web')
            ORDER BY users.source_type, users.source_key
            """,
            (user_id,),
        ).fetchall()
    return tuple(_row_to_subscription(source_registry, row) for row in rows)


def remove_user_source_subscription(
    database: Database,
    *,
    user_id: str,
    subscription_id: str,
    now: int | None = None,
) -> None:
    current = int(time.time()) if now is None else now
    with database.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        match = None
        rows = connection.execute(
            """
            SELECT source_type, source_key
            FROM source_sync_subscription_users
            WHERE user_id = ?
              AND source_type IN ('statuspage', 'rss_atom', 'json_feed', 'generic_web')
            """,
            (user_id,),
        ).fetchall()
        for row in rows:
            if _subscription_id(row["source_type"], row["source_key"]) == subscription_id:
                match = row
                break
        if match is None:
            connection.rollback()
            raise not_found("Source subscription was not found")
        source_type = match["source_type"]
        source_key = match["source_key"]
        connection.execute(
            """
            DELETE FROM source_sync_subscription_users
            WHERE source_type = ? AND source_key = ? AND user_id = ?
            """,
            (source_type, source_key, user_id),
        )
        remaining = connection.execute(
            """
            SELECT 1 FROM source_sync_subscription_users
            WHERE source_type = ? AND source_key = ?
            LIMIT 1
            """,
            (source_type, source_key),
        ).fetchone()
        if remaining is None:
            connection.execute(
                """
                UPDATE source_sync_subscriptions
                SET selected = 0
                WHERE source_type = ? AND source_key = ?
                """,
                (source_type, source_key),
            )
            connection.execute(
                """
                DELETE FROM source_sync_jobs
                WHERE source_type = ? AND source_key = ?
                  AND lease_until <= ?
                """,
                (source_type, source_key, current),
            )
        connection.commit()


def resolve_user_source_identity(
    settings: Settings,
    *,
    kind: str,
    url: str | None,
    page_id: str | None,
    registry: SourceRegistry,
    verification_status: str | None = None,
    authority_status: str | None = None,
) -> tuple[str, str, str, str | None]:
    """Validate and canonicalize before any subscription/job write.

    Returns ``(source_type, source_key, canonical_url, page_id)``.
    URL sources are allowlist/SSRF-checked via ``validate_feed_url`` first.
    """
    if kind not in USER_SOURCE_TYPES:
        raise unprocessable("Unsupported source kind")
    if kind == "statuspage":
        resolved_page_id = parse_statuspage_page_id(page_id=page_id, url=url)
        canonical_url = statuspage_canonical_url(resolved_page_id)
        endpoint = registry.register_endpoint(
            url=canonical_url,
            family=SourceKind.STATUSPAGE,
        )
        return "statuspage", resolved_page_id, endpoint.canonical_url, resolved_page_id

    if not url or not url.strip():
        raise unprocessable("url is required")
    if kind == "generic_web":
        if not settings.web_hosts:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Web fetching is disabled")
        validated = validate_web_url(url.strip(), settings.web_hosts)
        try:
            canonical = canonicalize_url(validated)
        except ValueError as exc:
            raise unprocessable(str(exc)) from exc
        family = SourceKind.GENERIC_WEB
        duplicate = registry.find_duplicate_endpoint(canonical, family=family)
        endpoint = duplicate or registry.register_endpoint(url=canonical, family=family)
        return kind, endpoint.canonical_url, endpoint.canonical_url, None
    if not settings.rss_hosts:
        from app.services.source_discovery_seeds import is_curated_subscribe_feed_url

        if not is_curated_subscribe_feed_url(url.strip()):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="RSS fetching is disabled")
    validated = validate_feed_url(url.strip(), settings.rss_hosts)
    try:
        canonical = canonicalize_url(validated)
    except ValueError as exc:
        raise unprocessable(str(exc)) from exc
    family = SourceKind.RSS_ATOM if kind == "rss_atom" else SourceKind.JSON_FEED
    duplicate = registry.find_duplicate_endpoint(canonical, family=family)
    desired = _resolved_rss_status(
        canonical,
        verification_status=verification_status,
        authority_status=authority_status,
    )
    if duplicate is None:
        endpoint = registry.register_endpoint(
            url=canonical,
            family=family,
            verification_status=desired[0] if desired else None,
            authority_status=desired[1] if desired else None,
        )
    else:
        endpoint = _align_endpoint_status(
            registry,
            duplicate,
            canonical,
            verification_status=desired[0] if desired else None,
            authority_status=desired[1] if desired else None,
        )
    return kind, endpoint.canonical_url, endpoint.canonical_url, None


def _japanese_registry_status(url: str) -> tuple[str, str] | None:
    from app.services.japanese_source_catalog import japanese_feed_authority_class

    authority_class = japanese_feed_authority_class(url)
    if authority_class == "community":
        return VerificationStatus.VERIFIED.value, AuthorityStatus.NON_AUTHORITATIVE.value
    if authority_class == "secondary":
        return VerificationStatus.VERIFIED.value, AuthorityStatus.UNKNOWN.value
    return None


def _resolved_rss_status(
    url: str,
    *,
    verification_status: str | None = None,
    authority_status: str | None = None,
) -> tuple[str, str] | None:
    """Catalog class wins. Candidate statuses may only keep a non-authoritative default."""
    catalog = _japanese_registry_status(url)
    if catalog is not None:
        return catalog
    if (
        verification_status
        and authority_status
        and authority_status != AuthorityStatus.AUTHORITATIVE.value
    ):
        return verification_status, authority_status
    return None


def _align_endpoint_status(
    registry: SourceRegistry,
    endpoint: Endpoint,
    url: str,
    verification_status: str | None = None,
    authority_status: str | None = None,
) -> Endpoint:
    desired = _resolved_rss_status(
        url,
        verification_status=verification_status,
        authority_status=authority_status,
    )
    if desired is None:
        return endpoint
    resolved_verification, resolved_authority = desired
    if (
        endpoint.verification_status == resolved_verification
        and endpoint.authority_status == resolved_authority
    ):
        return endpoint
    stamp = iso_timestamp(int(time.time())) or datetime.now(UTC).replace(microsecond=0).isoformat()
    verified = resolved_verification == VerificationStatus.VERIFIED.value
    return registry.record_verification(
        endpoint.endpoint_id,
        verification_status=resolved_verification,
        verification_method=(
            "japanese_source_catalog" if _japanese_registry_status(url) else "source_recommendation"
        ),
        verification_reference=url,
        verified_at=stamp if verified else None,
        authority_status=resolved_authority,
    )


def parse_statuspage_page_id(*, page_id: str | None, url: str | None) -> str:
    if page_id and page_id.strip():
        candidate = page_id.strip().lower()
    elif url and url.strip():
        parsed = urlparse(url.strip())
        if parsed.scheme and parsed.scheme.lower() not in {"http", "https"}:
            raise unprocessable("Statuspage URL must be HTTP or HTTPS")
        host = (parsed.hostname or "").lower().rstrip(".")
        if host.startswith("www."):
            host = host[4:]
        if not host.endswith(_STATUSPAGE_HOST_SUFFIX):
            raise unprocessable("Statuspage URL must use a statuspage.io page host")
        candidate = host[: -len(_STATUSPAGE_HOST_SUFFIX)]
        if not candidate or "." in candidate:
            raise unprocessable("Invalid Statuspage ID")
    else:
        raise unprocessable("pageId or url is required for statuspage")
    if not PAGE_ID_PATTERN.fullmatch(candidate):
        raise unprocessable("Invalid Statuspage ID")
    return candidate


def statuspage_canonical_url(page_id: str) -> str:
    return f"https://{page_id}.statuspage.io/api/v2/summary.json"


def iso_timestamp(value: int | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value, UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _subscription_id(source_type: str, source_key: str) -> str:
    if source_type == "statuspage":
        return endpoint_id(url=statuspage_canonical_url(source_key), family=source_type)
    return endpoint_id(url=source_key, family=source_type)


def _user_has_subscription(
    database: Database,
    *,
    user_id: str,
    source_type: str,
    source_key: str,
) -> bool:
    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT 1 FROM source_sync_subscription_users
            WHERE source_type = ? AND source_key = ? AND user_id = ?
            LIMIT 1
            """,
            (source_type, source_key, user_id),
        ).fetchone()
    return row is not None


def _load_user_subscription(
    database: Database,
    *,
    user_id: str,
    source_type: str,
    source_key: str,
    registry: SourceRegistry,
) -> UserSourceSubscription | None:
    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT users.source_type, users.source_key, subscriptions.selected,
                   jobs.last_success_at, jobs.last_attempt_at, jobs.failure_count, jobs.next_run_at
            FROM source_sync_subscription_users AS users
            JOIN source_sync_subscriptions AS subscriptions
              ON subscriptions.source_type = users.source_type
             AND subscriptions.source_key = users.source_key
            LEFT JOIN source_sync_jobs AS jobs
              ON jobs.source_type = users.source_type
             AND jobs.source_key = users.source_key
            WHERE users.user_id = ?
              AND users.source_type = ?
              AND users.source_key = ?
            """,
            (user_id, source_type, source_key),
        ).fetchone()
    if row is None:
        return None
    return _row_to_subscription(registry, row)


def _row_to_subscription(registry: SourceRegistry, row) -> UserSourceSubscription:
    source_type = row["source_type"]
    source_key = row["source_key"]
    canonical_url = statuspage_canonical_url(source_key) if source_type == "statuspage" else source_key
    endpoint = registry.find_duplicate_endpoint(canonical_url, family=source_type)
    publisher_slug = None
    publisher_display_name = None
    if endpoint is not None:
        publisher = registry.get_publisher(endpoint.publisher_id)
        if publisher is not None:
            publisher_slug = publisher.slug
            publisher_display_name = publisher.display_name
            canonical_url = endpoint.canonical_url
    if publisher_slug is None:
        host = urlparse(canonical_url).hostname
        publisher_slug = host
        publisher_display_name = host
    return UserSourceSubscription(
        id=_subscription_id(source_type, source_key),
        kind=source_type,
        canonical_url=canonical_url,
        page_id=source_key if source_type == "statuspage" else None,
        publisher_slug=publisher_slug,
        publisher_display_name=publisher_display_name,
        selected=bool(row["selected"]),
        last_success_at=row["last_success_at"],
        last_attempt_at=row["last_attempt_at"],
        failure_count=int(row["failure_count"] or 0),
        next_run_at=row["next_run_at"],
    )
