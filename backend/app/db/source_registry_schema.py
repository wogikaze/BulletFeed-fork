from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.database import Database

SOURCE_REGISTRY_SCHEMA = """
CREATE TABLE IF NOT EXISTS source_publishers (
    publisher_id TEXT PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    homepage_url TEXT NOT NULL,
    aliases_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_endpoints (
    endpoint_id TEXT PRIMARY KEY,
    publisher_id TEXT NOT NULL,
    family TEXT NOT NULL,
    canonical_url TEXT NOT NULL,
    registered_url TEXT NOT NULL,
    discovery_method TEXT NOT NULL,
    verification_status TEXT NOT NULL,
    authority_status TEXT NOT NULL,
    previous_endpoint_id TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(publisher_id) REFERENCES source_publishers(publisher_id),
    FOREIGN KEY(previous_endpoint_id) REFERENCES source_endpoints(endpoint_id),
    UNIQUE(canonical_url, family)
);

CREATE INDEX IF NOT EXISTS idx_source_endpoints_publisher
ON source_endpoints(publisher_id, family);

CREATE INDEX IF NOT EXISTS idx_source_endpoints_canonical
ON source_endpoints(canonical_url);

CREATE TABLE IF NOT EXISTS source_endpoint_lineage (
    from_endpoint_id TEXT NOT NULL,
    to_endpoint_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    PRIMARY KEY(from_endpoint_id, to_endpoint_id, reason),
    FOREIGN KEY(from_endpoint_id) REFERENCES source_endpoints(endpoint_id),
    FOREIGN KEY(to_endpoint_id) REFERENCES source_endpoints(endpoint_id)
);

CREATE INDEX IF NOT EXISTS idx_source_endpoint_lineage_to
ON source_endpoint_lineage(to_endpoint_id, recorded_at);
"""


def ensure_source_registry_schema(database: Database) -> None:
    with database.connect() as connection:
        connection.executescript(SOURCE_REGISTRY_SCHEMA)
