LEDGER_SCHEMA = """
CREATE TABLE IF NOT EXISTS observations (
    id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    source_key TEXT NOT NULL,
    source_observation_id TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    original_url TEXT NOT NULL,
    published_at TEXT,
    retrieved_at TEXT NOT NULL,
    UNIQUE(source_type, source_key, source_observation_id, payload_hash)
);

CREATE INDEX IF NOT EXISTS idx_observations_source
ON observations(source_type, source_key, source_observation_id, retrieved_at);
"""
