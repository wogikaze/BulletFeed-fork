from __future__ import annotations

from app.database import Database


def ensure_projection_schema(database: Database) -> None:
    """Ensure derived projection indexes exist after revision-based initialize()."""
    with database.connect() as connection:
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_deltas_event_active "
            "ON deltas(event_id, active, occurred_at, id)"
        )
