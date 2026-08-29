from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.database import Database

SOURCE_DISCOVERY_SCHEMA = """
CREATE TABLE IF NOT EXISTS source_discovery_decisions (
    user_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    decided_at TEXT NOT NULL,
    PRIMARY KEY (user_id, candidate_id),
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_source_discovery_decisions_user
ON source_discovery_decisions(user_id, decision, decided_at);
"""


def ensure_source_discovery_schema(database: Database) -> None:
    with database.connect() as connection:
        connection.executescript(SOURCE_DISCOVERY_SCHEMA)
