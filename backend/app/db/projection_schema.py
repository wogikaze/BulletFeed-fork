from __future__ import annotations

from app.database import Database


def ensure_projection_schema(database: Database) -> None:
    """Migrate derived projection tables without changing raw ledger history."""
    with database.connect() as connection:
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(deltas)").fetchall()
        }
        if "active" not in columns:
            connection.execute(
                "ALTER TABLE deltas ADD COLUMN active INTEGER NOT NULL DEFAULT 1"
            )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_deltas_event_active "
            "ON deltas(event_id, active, occurred_at, id)"
        )
