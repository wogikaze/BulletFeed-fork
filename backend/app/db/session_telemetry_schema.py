SESSION_TELEMETRY_TABLES = ("feed_sessions", "feed_session_outcomes")

SESSION_TELEMETRY_SCHEMA = """
CREATE TABLE IF NOT EXISTS feed_sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    started_at INTEGER NOT NULL,
    ended_at INTEGER,
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_feed_sessions_user
ON feed_sessions(user_id, started_at, id);

CREATE TABLE IF NOT EXISTS feed_session_outcomes (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    feed_item_id TEXT,
    feedback_type TEXT,
    created_at INTEGER NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id),
    FOREIGN KEY(session_id) REFERENCES feed_sessions(id)
);

CREATE INDEX IF NOT EXISTS idx_feed_session_outcomes_user
ON feed_session_outcomes(user_id, session_id, created_at, id);
"""
