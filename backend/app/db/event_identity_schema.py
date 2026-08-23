import sqlite3

from app.database import Database

EVENT_IDENTITY_SCHEMA = """
CREATE TABLE IF NOT EXISTS event_identity_aliases (
    alias_key TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    decision_version TEXT NOT NULL DEFAULT 'manual-v1',
    created_at TEXT NOT NULL,
    FOREIGN KEY(event_id) REFERENCES ledger_events(id)
);

CREATE INDEX IF NOT EXISTS idx_event_identity_aliases_event
ON event_identity_aliases(event_id, alias_key);

CREATE TABLE IF NOT EXISTS event_identity_repairs (
    id TEXT PRIMARY KEY,
    operation TEXT NOT NULL,
    source_event_id TEXT NOT NULL,
    target_event_id TEXT NOT NULL,
    claim_ids_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_event_identity_repairs_source
ON event_identity_repairs(source_event_id, created_at, id);
"""


def ensure_event_identity_schema(database: Database) -> None:
    with database.connect() as connection:
        connection.executescript(EVENT_IDENTITY_SCHEMA)
        migrations = (
            (
                "ALTER TABLE event_identity_aliases ADD COLUMN decision_version "
                "TEXT NOT NULL DEFAULT 'manual-v1'"
            ),
            "ALTER TABLE event_identity_repairs ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'",
        )
        for statement in migrations:
            try:
                connection.execute(statement)
            except sqlite3.OperationalError:
                pass
