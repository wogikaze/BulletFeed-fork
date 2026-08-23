DISCOVERY_SCHEMA = """
CREATE TABLE IF NOT EXISTS discovery_candidates (
    id TEXT PRIMARY KEY,
    discovery_method TEXT NOT NULL,
    discovery_url TEXT NOT NULL,
    target_url TEXT NOT NULL,
    publisher_timestamp TEXT,
    metadata_json TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    UNIQUE(discovery_method, discovery_url, target_url)
);
CREATE INDEX IF NOT EXISTS idx_discovery_candidates_target
    ON discovery_candidates(target_url);
CREATE INDEX IF NOT EXISTS idx_discovery_candidates_last_seen
    ON discovery_candidates(last_seen_at DESC);
"""
