"""Personal knowledge-evidence audit log.

Revision 10. User-scoped only: account deletion removes these rows.
Factual ledger tables (events, deltas, state_claims, observations, ...) are
never written or deleted by this schema.
"""

KNOWLEDGE_EVIDENCE_TABLE = "user_knowledge_evidence"

KNOWLEDGE_EVIDENCE_SCHEMA = """
CREATE TABLE IF NOT EXISTS user_knowledge_evidence (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    claim_id TEXT,
    event_id TEXT,
    delta_id TEXT,
    kind TEXT NOT NULL,
    provenance TEXT NOT NULL,
    confidence TEXT NOT NULL,
    source_id TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_user_knowledge_evidence_idempotent
ON user_knowledge_evidence(user_id, kind, source_id);

CREATE INDEX IF NOT EXISTS idx_user_knowledge_evidence_target
ON user_knowledge_evidence(user_id, claim_id, event_id, delta_id, created_at, id);

CREATE INDEX IF NOT EXISTS idx_user_knowledge_evidence_user
ON user_knowledge_evidence(user_id, created_at, id);
"""
