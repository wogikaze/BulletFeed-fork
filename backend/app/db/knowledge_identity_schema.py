"""Derived semantic knowledge identity.

Revision 13. Deterministic claim→knowledge mapping. These tables are a
rebuildable index over claim text, not user-scoped evidence and not the
factual ledger (events, deltas, state_claims, observations).
"""

KNOWLEDGE_IDENTITY_TABLE = "knowledge_identities"
CLAIM_KNOWLEDGE_MAP_TABLE = "claim_knowledge_map"

KNOWLEDGE_IDENTITY_SCHEMA = """
CREATE TABLE IF NOT EXISTS knowledge_identities (
    id TEXT PRIMARY KEY,
    fingerprint_json TEXT NOT NULL,
    version TEXT NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS claim_knowledge_map (
    claim_id TEXT PRIMARY KEY,
    knowledge_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    confidence TEXT NOT NULL,
    version TEXT NOT NULL,
    decision TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    FOREIGN KEY(knowledge_id) REFERENCES knowledge_identities(id)
);

CREATE INDEX IF NOT EXISTS idx_claim_knowledge_map_knowledge
ON claim_knowledge_map(knowledge_id, claim_id);
"""
