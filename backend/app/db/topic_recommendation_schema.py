"""User decisions on topic recommendations. Does not write topics or ledger state."""

from __future__ import annotations

from app.database import Database

TOPIC_RECOMMENDATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS topic_recommendation_decisions (
    user_id TEXT NOT NULL,
    topic_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    decided_at INTEGER NOT NULL,
    PRIMARY KEY (user_id, topic_id)
);
"""


def ensure_topic_recommendation_schema(database: Database) -> None:
    with database.connect() as connection:
        connection.executescript(TOPIC_RECOMMENDATION_SCHEMA)
