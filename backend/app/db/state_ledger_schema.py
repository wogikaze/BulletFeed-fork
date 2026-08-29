STATE_LEDGER_SCHEMA = """
CREATE TABLE IF NOT EXISTS ledger_events (
    id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    source_key TEXT NOT NULL,
    source_event_id TEXT NOT NULL,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(source_type, source_key, source_event_id)
);

CREATE TABLE IF NOT EXISTS state_claims (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    observation_id TEXT NOT NULL,
    slot TEXT NOT NULL,
    value_text TEXT NOT NULL,
    detail_text TEXT NOT NULL,
    valid_at TEXT NOT NULL,
    source_updated_at TEXT NOT NULL DEFAULT '',
    revision_hint TEXT NOT NULL DEFAULT '',
    observed_at TEXT NOT NULL,
    FOREIGN KEY(event_id) REFERENCES ledger_events(id),
    FOREIGN KEY(observation_id) REFERENCES observations(id)
);

CREATE INDEX IF NOT EXISTS idx_state_claims_event_slot
ON state_claims(event_id, slot, valid_at, id);

CREATE TABLE IF NOT EXISTS claim_relations (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    prior_claim_id TEXT,
    new_claim_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    decision_reason TEXT NOT NULL DEFAULT '',
    decision_confidence TEXT NOT NULL DEFAULT 'high',
    decision_version TEXT NOT NULL DEFAULT 'legacy',
    decision_abstained INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(event_id) REFERENCES ledger_events(id),
    FOREIGN KEY(prior_claim_id) REFERENCES state_claims(id),
    FOREIGN KEY(new_claim_id) REFERENCES state_claims(id)
);

CREATE TABLE IF NOT EXISTS claim_evidence (
    id TEXT PRIMARY KEY,
    claim_id TEXT NOT NULL,
    observation_id TEXT NOT NULL,
    original_url TEXT NOT NULL,
    evidence_text TEXT NOT NULL,
    dependence_key TEXT NOT NULL DEFAULT '',
    published_at TEXT,
    retrieved_at TEXT NOT NULL,
    FOREIGN KEY(claim_id) REFERENCES state_claims(id),
    FOREIGN KEY(observation_id) REFERENCES observations(id)
);

CREATE TABLE IF NOT EXISTS delta_claim_map (
    delta_id TEXT PRIMARY KEY,
    claim_id TEXT NOT NULL UNIQUE,
    event_id TEXT NOT NULL,
    FOREIGN KEY(claim_id) REFERENCES state_claims(id),
    FOREIGN KEY(event_id) REFERENCES ledger_events(id)
);

CREATE TABLE IF NOT EXISTS event_source_claim_map (
    source_id TEXT PRIMARY KEY,
    claim_id TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    FOREIGN KEY(source_id) REFERENCES event_sources(id),
    FOREIGN KEY(claim_id) REFERENCES state_claims(id),
    FOREIGN KEY(evidence_id) REFERENCES claim_evidence(id)
);

CREATE TABLE IF NOT EXISTS user_claim_exposures (
    user_id TEXT NOT NULL,
    claim_id TEXT NOT NULL,
    delivery_id TEXT NOT NULL,
    delivered_at TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'displayed',
    displayed_at TEXT,
    read_at TEXT,
    delivery_count INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY(user_id, claim_id),
    FOREIGN KEY(user_id) REFERENCES users(id),
    FOREIGN KEY(claim_id) REFERENCES state_claims(id),
    FOREIGN KEY(delivery_id) REFERENCES deliveries(id)
);

CREATE INDEX IF NOT EXISTS idx_user_claim_exposures_user
ON user_claim_exposures(user_id, delivered_at, claim_id);

CREATE INDEX IF NOT EXISTS idx_user_claim_exposures_state
ON user_claim_exposures(user_id, state, claim_id);

CREATE TABLE IF NOT EXISTS event_visibility (
    event_id TEXT PRIMARY KEY,
    restricted INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(event_id) REFERENCES events(id)
);

CREATE TABLE IF NOT EXISTS event_user_access (
    event_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    expires_at INTEGER NOT NULL,
    PRIMARY KEY(event_id, user_id),
    FOREIGN KEY(event_id) REFERENCES events(id),
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_event_user_access_user
ON event_user_access(user_id, expires_at, event_id);
"""
