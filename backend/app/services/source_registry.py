from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlparse, urlunparse

from app.database import Database
from app.db.source_registry_schema import SOURCE_REGISTRY_SCHEMA
from app.services.source_catalog import (
    DiscoveryMethod,
    SourceKind,
    SourcePolicy,
    get_source_policy,
    source_allows_claim_evidence,
)

TRACKING_QUERY_PARAMS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "utm_id",
        "utm_cid",
        "gclid",
        "fbclid",
        "mc_cid",
        "mc_eid",
        "ref",
        "ref_src",
        "_ga",
        "spm",
    }
)

MVP_SEEDED_AT = "2026-01-01T00:00:00Z"
_MULTI_SLASH = re.compile(r"/{2,}")


class VerificationStatus(StrEnum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    DISCOVERY_ONLY = "discovery_only"


class AuthorityStatus(StrEnum):
    UNKNOWN = "unknown"
    AUTHORITATIVE = "authoritative"
    NON_AUTHORITATIVE = "non_authoritative"


@dataclass(frozen=True)
class Publisher:
    publisher_id: str
    slug: str
    display_name: str
    homepage_url: str
    aliases: tuple[str, ...]
    created_at: str


@dataclass(frozen=True)
class Endpoint:
    endpoint_id: str
    publisher_id: str
    family: str
    canonical_url: str
    registered_url: str
    discovery_method: str
    verification_status: str
    authority_status: str
    created_at: str
    previous_endpoint_id: str | None = None
    verification_method: str | None = None
    verification_reference: str | None = None
    verified_at: str | None = None
    authority_method: str | None = None
    authority_reference: str | None = None
    authority_verified_at: str | None = None

    @property
    def redirect_of(self) -> str | None:
        return self.previous_endpoint_id


@dataclass(frozen=True)
class EndpointLineage:
    from_endpoint_id: str
    to_endpoint_id: str
    reason: str
    recorded_at: str


@dataclass(frozen=True)
class _SeedEndpoint:
    url: str
    family: SourceKind


@dataclass(frozen=True)
class _SeedPublisher:
    slug: str
    display_name: str
    homepage_url: str
    aliases: tuple[str, ...]
    endpoints: tuple[_SeedEndpoint, ...]


# Official catalog families as discoverable registry entries. Concrete hosts stay
# distinct unless an explicit publisher slug/alias attaches them.
MVP_PUBLISHERS: tuple[_SeedPublisher, ...] = (
    _SeedPublisher(
        slug="github",
        display_name="GitHub",
        homepage_url="https://github.com",
        aliases=("https://www.github.com", "https://api.github.com", "https://github.blog"),
        endpoints=(
            _SeedEndpoint("https://api.github.com", SourceKind.GITHUB_RELEASE),
            _SeedEndpoint("https://api.github.com", SourceKind.GITHUB_SBOM),
            _SeedEndpoint("https://api.github.com/advisories", SourceKind.GITHUB_ADVISORY),
            _SeedEndpoint("https://github.blog/feed/", SourceKind.RSS_ATOM),
        ),
    ),
    _SeedPublisher(
        slug="osv",
        display_name="OSV",
        homepage_url="https://osv.dev",
        aliases=("https://api.osv.dev",),
        endpoints=(
            _SeedEndpoint("https://api.osv.dev/v1/query", SourceKind.OSV),
            _SeedEndpoint("https://api.osv.dev/v1/querybatch", SourceKind.OSV),
        ),
    ),
    _SeedPublisher(
        slug="statuspage",
        display_name="Atlassian Statuspage",
        homepage_url="https://www.statuspage.io",
        aliases=("https://meta.statuspage.io",),
        endpoints=(
            _SeedEndpoint(
                "https://meta.statuspage.io/api/v2/summary.json",
                SourceKind.STATUSPAGE,
            ),
        ),
    ),
    _SeedPublisher(
        slug="jsonfeed",
        display_name="JSON Feed",
        homepage_url="https://www.jsonfeed.org",
        aliases=(),
        endpoints=(_SeedEndpoint("https://www.jsonfeed.org/feed.json", SourceKind.JSON_FEED),),
    ),
    _SeedPublisher(
        slug="hacker-news",
        display_name="Hacker News",
        homepage_url="https://news.ycombinator.com",
        aliases=("https://hacker-news.firebaseio.com",),
        endpoints=(
            _SeedEndpoint(
                "https://hacker-news.firebaseio.com/v0/topstories.json",
                SourceKind.HACKER_NEWS_DISCOVERY,
            ),
        ),
    ),
)


def canonicalize_url(url: str) -> str:
    """Normalize trivial URL variants without collapsing unrelated hosts.

    Policy: strip fragments and credentials; drop default ports; treat http/https
    as the same host identity (store https); strip a leading ``www.`` label;
    drop common tracking query params and sort the rest; strip a trailing slash
    except on the site root. Subdomains such as ``status.github.com`` stay distinct
    from ``github.com``.
    """
    if not isinstance(url, str) or not url.strip():
        raise ValueError("url is required")
    parsed = urlparse(url.strip())
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError(f"unsupported URL scheme: {parsed.scheme!r}")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("url has no hostname")
    host = hostname.lower().rstrip(".")
    if not _is_ip_address(host) and host.startswith("www."):
        host = host[4:]
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError(f"invalid hostname: {hostname!r}") from exc
    port = parsed.port
    netloc = host if port in {None, 80, 443} else f"{host}:{port}"
    path = parsed.path or "/"
    path = quote(_MULTI_SLASH.sub("/", unquote(path)), safe="/-._~")
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    query_pairs = sorted(
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in TRACKING_QUERY_PARAMS
    )
    return urlunparse(("https", netloc, path, "", urlencode(query_pairs, doseq=True), ""))


def normalize_publisher_slug(slug: str) -> str:
    normalized = re.sub(r"[\s_]+", "-", slug.strip().lower())
    normalized = re.sub(r"-{2,}", "-", normalized).strip("-")
    if not normalized:
        raise ValueError("publisher slug is required")
    return normalized


def publisher_id(*, slug: str | None = None, homepage_url: str | None = None) -> str:
    if slug and slug.strip():
        return _stable_id("pub", normalize_publisher_slug(slug))
    if homepage_url:
        host = urlparse(canonicalize_url(homepage_url)).hostname
        if not host:
            raise ValueError("homepage_url has no hostname")
        return _stable_id("pub", host)
    raise ValueError("publisher_id requires slug or homepage_url")


def endpoint_id(*, url: str, family: str | SourceKind) -> str:
    return _stable_id("ep", canonicalize_url(url), _family_value(family))


def endpoint_allows_claim_evidence(endpoint: Endpoint) -> bool:
    """Fail closed: unknown family or discovery_only cannot back Claims."""
    return source_allows_claim_evidence(_family_value(endpoint.family))


class SourceRegistry:
    """Canonical publisher/endpoint identity. Does not schedule or fetch.

    Duplicate detection happens before scheduling: ``register_endpoint`` returns
    the existing id when the canonical URL+family is already registered.
    Redirects record lineage only; Observation.source_key is never rewritten.
    """

    def __init__(self, database: Database | None = None, *, seed_mvp: bool = True) -> None:
        self._database = database
        self._publishers: dict[str, Publisher] = {}
        self._endpoints: dict[str, Endpoint] = {}
        self._lineage: list[EndpointLineage] = []
        self._identity_index: dict[tuple[str, str], str] = {}
        self._host_index: dict[str, str] = {}
        if database is not None:
            self._ensure_schema()
            self._load()
        if seed_mvp:
            self.seed_mvp()

    def seed_mvp(self) -> None:
        for seed in MVP_PUBLISHERS:
            self.register_publisher(
                slug=seed.slug,
                display_name=seed.display_name,
                homepage_url=seed.homepage_url,
                aliases=seed.aliases,
                created_at=MVP_SEEDED_AT,
            )
            for item in seed.endpoints:
                self.register_endpoint(
                    url=item.url,
                    family=item.family,
                    publisher_slug=seed.slug,
                    created_at=MVP_SEEDED_AT,
                )

    def register_publisher(
        self,
        *,
        slug: str,
        display_name: str,
        homepage_url: str,
        aliases: Iterable[str] = (),
        created_at: str | None = None,
    ) -> Publisher:
        normalized_slug = normalize_publisher_slug(slug)
        canonical_home = canonicalize_url(homepage_url)
        identity = publisher_id(slug=normalized_slug)
        new_aliases = self._canonical_aliases(aliases, extra=(canonical_home,))
        existing = self._publishers.get(identity)
        if existing is not None:
            merged = tuple(sorted(set(existing.aliases) | set(new_aliases)))
            if merged != existing.aliases:
                existing = replace(existing, aliases=merged)
                self._publishers[identity] = existing
                self._index_publisher(existing)
                self._persist_publisher(existing)
            return existing
        publisher = Publisher(
            publisher_id=identity,
            slug=normalized_slug,
            display_name=display_name.strip() or normalized_slug,
            homepage_url=canonical_home,
            aliases=new_aliases,
            created_at=created_at or _utc_now(),
        )
        self._publishers[identity] = publisher
        self._index_publisher(publisher)
        self._persist_publisher(publisher)
        return publisher

    def register_endpoint(
        self,
        *,
        url: str,
        family: str | SourceKind,
        publisher_id: str | None = None,
        publisher_slug: str | None = None,
        discovery_method: str | DiscoveryMethod | None = None,
        verification_status: str | VerificationStatus | None = None,
        authority_status: str | AuthorityStatus | None = None,
        verification_method: str | None = None,
        verification_reference: str | None = None,
        verified_at: str | None = None,
        authority_method: str | None = None,
        authority_reference: str | None = None,
        authority_verified_at: str | None = None,
        created_at: str | None = None,
    ) -> Endpoint:
        """Register an endpoint or return the existing row for the same identity."""
        duplicate = self.find_duplicate_endpoint(url, family=family)
        if duplicate is not None:
            return duplicate
        family_value = _family_value(family)
        canonical = canonicalize_url(url)
        policy = _catalog_policy(family_value)
        resolved_publisher = self._resolve_publisher_id(
            publisher_id=publisher_id,
            publisher_slug=publisher_slug,
            url=canonical,
            created_at=created_at,
        )
        endpoint = Endpoint(
            endpoint_id=endpoint_id(url=canonical, family=family_value),
            publisher_id=resolved_publisher,
            family=family_value,
            canonical_url=canonical,
            registered_url=url.strip(),
            discovery_method=_enum_value(discovery_method) or _default_discovery_method(policy),
            verification_status=_enum_value(verification_status)
            or _default_verification_status(policy),
            authority_status=_enum_value(authority_status) or _default_authority_status(policy),
            created_at=created_at or _utc_now(),
            verification_method=verification_method,
            verification_reference=verification_reference,
            verified_at=verified_at,
            authority_method=authority_method,
            authority_reference=authority_reference,
            authority_verified_at=authority_verified_at,
        )
        self._store_endpoint(endpoint)
        self._persist_endpoint(endpoint)
        return endpoint

    def find_duplicate_endpoint(
        self,
        url: str,
        family: str | SourceKind | None = None,
    ) -> Endpoint | None:
        canonical = canonicalize_url(url)
        if family is not None:
            identity = self._identity_index.get((canonical, _family_value(family)))
            return self._endpoints.get(identity) if identity else None
        matches = sorted(
            (
                endpoint
                for endpoint in self._endpoints.values()
                if endpoint.canonical_url == canonical
            ),
            key=lambda item: item.endpoint_id,
        )
        return matches[0] if matches else None

    def detect_duplicate(
        self,
        url: str,
        family: str | SourceKind | None = None,
    ) -> Endpoint | None:
        return self.find_duplicate_endpoint(url, family=family)

    def record_redirect(
        self,
        *,
        previous_url: str,
        current_url: str,
        family: str | SourceKind,
        reason: str = "redirect",
        publisher_id: str | None = None,
        publisher_slug: str | None = None,
        recorded_at: str | None = None,
    ) -> Endpoint:
        """Preserve moved-feed lineage without rewriting Observations."""
        family_value = _family_value(family)
        previous_canonical = canonicalize_url(previous_url)
        current_canonical = canonicalize_url(current_url)
        if previous_canonical == current_canonical:
            raise ValueError("redirect URLs canonicalize to the same endpoint")
        previous = self.register_endpoint(
            url=previous_url,
            family=family_value,
            publisher_id=publisher_id,
            publisher_slug=publisher_slug,
            created_at=recorded_at,
        )
        current = self.register_endpoint(
            url=current_url,
            family=family_value,
            publisher_id=publisher_id or previous.publisher_id,
            publisher_slug=publisher_slug,
            created_at=recorded_at,
        )
        current = self._attach_previous(current, previous.endpoint_id)
        stamp = recorded_at or _utc_now()
        lineage = EndpointLineage(
            from_endpoint_id=previous.endpoint_id,
            to_endpoint_id=current.endpoint_id,
            reason=reason,
            recorded_at=stamp,
        )
        if not any(
            row.from_endpoint_id == lineage.from_endpoint_id
            and row.to_endpoint_id == lineage.to_endpoint_id
            and row.reason == lineage.reason
            for row in self._lineage
        ):
            self._lineage.append(lineage)
            self._persist_lineage(lineage)
        return current

    def record_verification(
        self,
        endpoint_id: str,
        *,
        verification_status: str | VerificationStatus,
        verification_method: str | None,
        verification_reference: str | None,
        verified_at: str | None,
        authority_status: str | AuthorityStatus,
        authority_method: str | None = None,
        authority_reference: str | None = None,
        authority_verified_at: str | None = None,
    ) -> Endpoint:
        """Record runtime verification evidence without changing endpoint identity."""
        endpoint = self.get_endpoint(endpoint_id)
        if endpoint is None:
            raise ValueError(f"unknown endpoint_id: {endpoint_id}")
        resolved_verification = _enum_value(verification_status)
        resolved_authority = _enum_value(authority_status)
        if resolved_verification not in {
            VerificationStatus.UNVERIFIED.value,
            VerificationStatus.VERIFIED.value,
            VerificationStatus.DISCOVERY_ONLY.value,
        }:
            raise ValueError(f"unknown verification status: {resolved_verification}")
        if resolved_authority not in {
            AuthorityStatus.UNKNOWN.value,
            AuthorityStatus.AUTHORITATIVE.value,
            AuthorityStatus.NON_AUTHORITATIVE.value,
        }:
            raise ValueError(f"unknown authority status: {resolved_authority}")
        if resolved_verification == VerificationStatus.VERIFIED.value and not all(
            (verification_method, verification_reference, verified_at)
        ):
            raise ValueError("verified endpoints require method, reference, and verified_at")
        if resolved_authority == AuthorityStatus.AUTHORITATIVE.value and not all(
            (authority_method, authority_reference, authority_verified_at)
        ):
            raise ValueError("authoritative endpoints require method, reference, and verified_at")
        updated = replace(
            endpoint,
            verification_status=resolved_verification,
            verification_method=verification_method,
            verification_reference=verification_reference,
            verified_at=verified_at,
            authority_status=resolved_authority,
            authority_method=authority_method,
            authority_reference=authority_reference,
            authority_verified_at=authority_verified_at,
        )
        self._store_endpoint(updated)
        self._persist_endpoint(updated)
        return updated

    def get_publisher(self, publisher_id: str) -> Publisher | None:
        return self._publishers.get(publisher_id)

    def find_publisher(self, *, slug: str | None = None, url: str | None = None) -> Publisher | None:
        if slug:
            return self._publishers.get(publisher_id(slug=slug))
        if url:
            canonical = canonicalize_url(url)
            host = urlparse(canonical).hostname
            for publisher in self._publishers.values():
                if canonical == publisher.homepage_url or canonical in publisher.aliases:
                    return publisher
            if host and host in self._host_index:
                return self._publishers.get(self._host_index[host])
        return None

    def get_endpoint(self, endpoint_id: str) -> Endpoint | None:
        return self._endpoints.get(endpoint_id)

    def list_publishers(self) -> tuple[Publisher, ...]:
        return tuple(sorted(self._publishers.values(), key=lambda item: item.slug))

    def list_endpoints(self, *, publisher_id: str | None = None) -> tuple[Endpoint, ...]:
        endpoints = self._endpoints.values()
        if publisher_id is not None:
            endpoints = (item for item in endpoints if item.publisher_id == publisher_id)
        return tuple(sorted(endpoints, key=lambda item: (item.family, item.canonical_url)))

    def lineage_for(self, endpoint_id: str) -> tuple[EndpointLineage, ...]:
        return tuple(
            row
            for row in self._lineage
            if row.from_endpoint_id == endpoint_id or row.to_endpoint_id == endpoint_id
        )

    def _resolve_publisher_id(
        self,
        *,
        publisher_id: str | None,
        publisher_slug: str | None,
        url: str,
        created_at: str | None,
    ) -> str:
        if publisher_id:
            if publisher_id not in self._publishers:
                raise ValueError(f"unknown publisher_id: {publisher_id}")
            return publisher_id
        if publisher_slug:
            existing = self.find_publisher(slug=publisher_slug)
            if existing is not None:
                return existing.publisher_id
            return self.register_publisher(
                slug=publisher_slug,
                display_name=publisher_slug,
                homepage_url=url,
                created_at=created_at,
            ).publisher_id
        host = urlparse(url).hostname
        if host and host in self._host_index:
            return self._host_index[host]
        if not host:
            raise ValueError("url has no hostname")
        return self.register_publisher(
            slug=host,
            display_name=host,
            homepage_url=f"https://{host}",
            created_at=created_at,
        ).publisher_id

    def _attach_previous(self, endpoint: Endpoint, previous_endpoint_id: str) -> Endpoint:
        if endpoint.previous_endpoint_id == previous_endpoint_id:
            return endpoint
        updated = replace(endpoint, previous_endpoint_id=previous_endpoint_id)
        self._store_endpoint(updated)
        self._persist_endpoint(updated)
        return updated

    def _store_endpoint(self, endpoint: Endpoint) -> None:
        self._endpoints[endpoint.endpoint_id] = endpoint
        self._identity_index[(endpoint.canonical_url, endpoint.family)] = endpoint.endpoint_id

    def _canonical_aliases(self, aliases: Iterable[str], *, extra: Iterable[str] = ()) -> tuple[str, ...]:
        values: set[str] = set()
        for raw in (*aliases, *extra):
            try:
                values.add(canonicalize_url(raw))
            except ValueError:
                host = raw.strip().lower().rstrip(".")
                if host.startswith("www."):
                    host = host[4:]
                if host:
                    values.add(canonicalize_url(f"https://{host}"))
        return tuple(sorted(values))

    def _index_publisher(self, publisher: Publisher) -> None:
        for host in _publisher_hosts(publisher):
            self._host_index.setdefault(host, publisher.publisher_id)

    def _ensure_schema(self) -> None:
        assert self._database is not None
        with self._database.connect() as connection:
            connection.executescript(SOURCE_REGISTRY_SCHEMA)

    def _load(self) -> None:
        assert self._database is not None
        with self._database.connect() as connection:
            for row in connection.execute(
                """
                SELECT publisher_id, slug, display_name, homepage_url, aliases_json, created_at
                FROM source_publishers
                ORDER BY slug
                """
            ):
                publisher = Publisher(
                    publisher_id=row["publisher_id"],
                    slug=row["slug"],
                    display_name=row["display_name"],
                    homepage_url=row["homepage_url"],
                    aliases=tuple(json.loads(row["aliases_json"])),
                    created_at=row["created_at"],
                )
                self._publishers[publisher.publisher_id] = publisher
                self._index_publisher(publisher)
            for row in connection.execute(
                """
                SELECT endpoint_id, publisher_id, family, canonical_url, registered_url,
                       discovery_method, verification_status, authority_status,
                       verification_method, verification_reference, verified_at,
                       authority_method, authority_reference, authority_verified_at,
                       previous_endpoint_id, created_at
                FROM source_endpoints
                ORDER BY endpoint_id
                """
            ):
                endpoint = Endpoint(
                    endpoint_id=row["endpoint_id"],
                    publisher_id=row["publisher_id"],
                    family=row["family"],
                    canonical_url=row["canonical_url"],
                    registered_url=row["registered_url"],
                    discovery_method=row["discovery_method"],
                    verification_status=row["verification_status"],
                    authority_status=row["authority_status"],
                    verification_method=row["verification_method"],
                    verification_reference=row["verification_reference"],
                    verified_at=row["verified_at"],
                    authority_method=row["authority_method"],
                    authority_reference=row["authority_reference"],
                    authority_verified_at=row["authority_verified_at"],
                    previous_endpoint_id=row["previous_endpoint_id"],
                    created_at=row["created_at"],
                )
                self._store_endpoint(endpoint)
            for row in connection.execute(
                """
                SELECT from_endpoint_id, to_endpoint_id, reason, recorded_at
                FROM source_endpoint_lineage
                ORDER BY recorded_at, from_endpoint_id, to_endpoint_id
                """
            ):
                self._lineage.append(
                    EndpointLineage(
                        from_endpoint_id=row["from_endpoint_id"],
                        to_endpoint_id=row["to_endpoint_id"],
                        reason=row["reason"],
                        recorded_at=row["recorded_at"],
                    )
                )

    def _persist_publisher(self, publisher: Publisher) -> None:
        if self._database is None:
            return
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO source_publishers (
                    publisher_id, slug, display_name, homepage_url, aliases_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(publisher_id) DO UPDATE SET
                    aliases_json = excluded.aliases_json
                """,
                (
                    publisher.publisher_id,
                    publisher.slug,
                    publisher.display_name,
                    publisher.homepage_url,
                    json.dumps(list(publisher.aliases), ensure_ascii=False, separators=(",", ":")),
                    publisher.created_at,
                ),
            )

    def _persist_endpoint(self, endpoint: Endpoint) -> None:
        if self._database is None:
            return
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO source_endpoints (
                    endpoint_id, publisher_id, family, canonical_url, registered_url,
                    discovery_method, verification_status, authority_status,
                    verification_method, verification_reference, verified_at,
                    authority_method, authority_reference, authority_verified_at,
                    previous_endpoint_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(endpoint_id) DO UPDATE SET
                    verification_status = excluded.verification_status,
                    verification_method = excluded.verification_method,
                    verification_reference = excluded.verification_reference,
                    verified_at = excluded.verified_at,
                    authority_status = excluded.authority_status,
                    authority_method = excluded.authority_method,
                    authority_reference = excluded.authority_reference,
                    authority_verified_at = excluded.authority_verified_at,
                    previous_endpoint_id = excluded.previous_endpoint_id
                """,
                (
                    endpoint.endpoint_id,
                    endpoint.publisher_id,
                    endpoint.family,
                    endpoint.canonical_url,
                    endpoint.registered_url,
                    endpoint.discovery_method,
                    endpoint.verification_status,
                    endpoint.authority_status,
                    endpoint.verification_method,
                    endpoint.verification_reference,
                    endpoint.verified_at,
                    endpoint.authority_method,
                    endpoint.authority_reference,
                    endpoint.authority_verified_at,
                    endpoint.previous_endpoint_id,
                    endpoint.created_at,
                ),
            )

    def _persist_lineage(self, lineage: EndpointLineage) -> None:
        if self._database is None:
            return
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO source_endpoint_lineage (
                    from_endpoint_id, to_endpoint_id, reason, recorded_at
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    lineage.from_endpoint_id,
                    lineage.to_endpoint_id,
                    lineage.reason,
                    lineage.recorded_at,
                ),
            )


def find_duplicate_endpoint(
    registry: SourceRegistry,
    url: str,
    family: str | SourceKind | None = None,
) -> Endpoint | None:
    return registry.find_duplicate_endpoint(url, family=family)


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "|".join(parts)
    return f"{prefix}_{hashlib.sha256(raw.encode()).hexdigest()[:24]}"


def _family_value(family: str | SourceKind) -> str:
    return family.value if isinstance(family, SourceKind) else str(family).strip()


def _enum_value(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, StrEnum):
        return value.value
    text = str(value).strip()
    return text or None


def _catalog_policy(family: str) -> SourcePolicy | None:
    try:
        return get_source_policy(SourceKind(family))
    except ValueError:
        return None


def _default_discovery_method(policy: SourcePolicy | None) -> str:
    if policy is None:
        return DiscoveryMethod.HTML.value
    return policy.discovery_method.value


def _default_verification_status(policy: SourcePolicy | None) -> str:
    if policy is None:
        return VerificationStatus.UNVERIFIED.value
    if policy.discovery_only:
        return VerificationStatus.DISCOVERY_ONLY.value
    return VerificationStatus.VERIFIED.value


def _default_authority_status(policy: SourcePolicy | None) -> str:
    if policy is None:
        return AuthorityStatus.UNKNOWN.value
    if policy.authoritative:
        return AuthorityStatus.AUTHORITATIVE.value
    return AuthorityStatus.NON_AUTHORITATIVE.value


def _publisher_hosts(publisher: Publisher) -> tuple[str, ...]:
    hosts: set[str] = set()
    for raw in (publisher.homepage_url, *publisher.aliases):
        host = urlparse(raw).hostname
        if host:
            hosts.add(host)
    return tuple(sorted(hosts))


def _is_ip_address(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return True


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
