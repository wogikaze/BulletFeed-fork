PUBLIC_API_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    created_at INTEGER NOT NULL,
    onboarding_completed INTEGER NOT NULL DEFAULT 0,
    onboarding_state TEXT NOT NULL DEFAULT 'profile',
    github_connected INTEGER NOT NULL DEFAULT 0,
    github_credential_state TEXT NOT NULL DEFAULT 'disconnected',
    github_user_id INTEGER,
    github_login TEXT
);

CREATE TABLE IF NOT EXISTS user_sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    expires_at INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS user_refresh_tokens (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    expires_at INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    rotated_at INTEGER,
    revoked_at INTEGER,
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_user_refresh_tokens_user
ON user_refresh_tokens(user_id, expires_at);

CREATE TABLE IF NOT EXISTS profiles (
    user_id TEXT PRIMARY KEY,
    occupation TEXT NOT NULL DEFAULT '',
    interests_json TEXT NOT NULL DEFAULT '[]',
    region TEXT NOT NULL DEFAULT '',
    updated_at INTEGER NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS topic_catalog (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    type TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS topics (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'technology',
    priority TEXT NOT NULL DEFAULT 'normal',
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    current_phase TEXT NOT NULL,
    current_summary TEXT NOT NULL,
    current_since TEXT NOT NULL,
    current_confidence TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS deltas (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    type TEXT NOT NULL,
    summary TEXT NOT NULL,
    before_text TEXT NOT NULL,
    after_text TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    FOREIGN KEY(event_id) REFERENCES events(id)
);

CREATE TABLE IF NOT EXISTS event_impacts (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    confidence TEXT NOT NULL,
    FOREIGN KEY(event_id) REFERENCES events(id)
);

CREATE TABLE IF NOT EXISTS source_policies (
    source_kind TEXT PRIMARY KEY,
    authority TEXT NOT NULL,
    terms_url TEXT,
    content_license TEXT,
    retain_raw INTEGER NOT NULL DEFAULT 0,
    redistribution TEXT NOT NULL,
    retention_days INTEGER,
    private_scope TEXT NOT NULL,
    policy_version TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS event_sources (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    publisher TEXT NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    published_at TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    evidence TEXT NOT NULL,
    FOREIGN KEY(event_id) REFERENCES events(id)
);

CREATE TABLE IF NOT EXISTS event_timeline (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    delta_id TEXT,
    type TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    state_before TEXT,
    state_after TEXT,
    FOREIGN KEY(event_id) REFERENCES events(id)
);

CREATE TABLE IF NOT EXISTS feed_items (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    delta_id TEXT NOT NULL,
    title TEXT NOT NULL,
    importance_level TEXT NOT NULL,
    importance_reason TEXT NOT NULL,
    importance_confidence TEXT NOT NULL,
    relation_level TEXT NOT NULL,
    relation_reason TEXT NOT NULL,
    matched_topics_json TEXT NOT NULL,
    matched_repos_json TEXT NOT NULL,
    personalization_rank INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'unread',
    dismissed INTEGER NOT NULL DEFAULT 0,
    marked_important INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    UNIQUE(user_id, delta_id),
    FOREIGN KEY(user_id) REFERENCES users(id),
    FOREIGN KEY(event_id) REFERENCES events(id),
    FOREIGN KEY(delta_id) REFERENCES deltas(id)
);

CREATE TABLE IF NOT EXISTS deliveries (
    id TEXT PRIMARY KEY,
    feed_item_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(feed_item_id) REFERENCES feed_items(id),
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS exposures (
    delivery_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    displayed_at TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    dwell_ms INTEGER,
    visible_ratio REAL,
    policy_version TEXT,
    detail_opened INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS feedback (
    id TEXT PRIMARY KEY,
    feed_item_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    type TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    event_id TEXT,
    delta_id TEXT,
    claim_id TEXT,
    family TEXT,
    superseded INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(feed_item_id) REFERENCES feed_items(id),
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_feedback_latest
ON feedback(user_id, feed_item_id, family, superseded, created_at, id);

CREATE TABLE IF NOT EXISTS user_knowledge_signals (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    feed_item_id TEXT,
    event_id TEXT,
    delta_id TEXT,
    claim_id TEXT,
    signal TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    superseded INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_user_knowledge_signals_latest
ON user_knowledge_signals(user_id, event_id, delta_id, claim_id, superseded);

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

CREATE TABLE IF NOT EXISTS user_ranking_resets (
    user_id TEXT PRIMARY KEY,
    reset_at INTEGER NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS user_ranking_features (
    user_id TEXT NOT NULL,
    feature_kind TEXT NOT NULL,
    feature_value TEXT NOT NULL,
    important_count INTEGER NOT NULL,
    not_relevant_count INTEGER NOT NULL,
    follow_count INTEGER NOT NULL DEFAULT 0,
    already_knew_count INTEGER NOT NULL DEFAULT 0,
    learned_now_count INTEGER NOT NULL DEFAULT 0,
    less_like_this_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, feature_kind, feature_value),
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS event_follows (
    user_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    following INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY(user_id, event_id),
    FOREIGN KEY(user_id) REFERENCES users(id),
    FOREIGN KEY(event_id) REFERENCES events(id)
);

CREATE TABLE IF NOT EXISTS github_repo_watches (
    user_id TEXT NOT NULL,
    repository_id TEXT NOT NULL,
    full_name TEXT NOT NULL,
    html_url TEXT NOT NULL DEFAULT '',
    selected INTEGER NOT NULL DEFAULT 1,
    private INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(user_id, repository_id),
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS security_alerts (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    advisory_id TEXT NOT NULL,
    cve TEXT,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    severity TEXT NOT NULL,
    status TEXT NOT NULL,
    repository_id TEXT,
    repository_full_name TEXT NOT NULL,
    package_name TEXT NOT NULL,
    current_version TEXT NOT NULL,
    fixed_version TEXT,
    dependency_type TEXT NOT NULL,
    detected_at TEXT NOT NULL,
    source TEXT NOT NULL,
    evidence TEXT NOT NULL,
    recommendation TEXT NOT NULL,
    cvss_score REAL,
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS notifications (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    category TEXT NOT NULL,
    priority TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    read INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(user_id) REFERENCES users(id)
);

INSERT OR IGNORE INTO source_policies (
    source_kind, authority, terms_url, content_license, retain_raw,
    redistribution, retention_days, private_scope, policy_version
) VALUES
    ('statuspage', 'first_party_status', NULL, 'provider_terms', 0, 'link_excerpt', 365, 'public', '2026-08-23'),
    ('github_advisory', 'security_advisory', NULL, 'provider_terms', 0, 'link_excerpt', 3650, 'public', '2026-08-23'),
    ('osv', 'security_database', NULL, 'source_specific', 0, 'link_excerpt', 3650, 'public', '2026-08-23'),
    ('github_release', 'first_party_repository', NULL, 'repository_specific', 0, 'link_excerpt', 365, 'repository', '2026-08-23'),
    ('github_sbom', 'user_repository', NULL, 'private_or_repository_specific', 0, 'none', 30, 'user_repository', '2026-08-23'),
    ('rss_atom', 'publisher_feed', NULL, 'publisher_specific', 0, 'link_excerpt', 90, 'public', '2026-08-23'),
    ('json_feed', 'publisher_feed', NULL, 'publisher_specific', 0, 'link_excerpt', 90, 'public', '2026-08-23'),
    ('official_changelog', 'first_party_changelog', NULL, 'publisher_specific', 0, 'link_excerpt', 365, 'public', '2026-08-23'),
    ('documentation', 'first_party_documentation', NULL, 'publisher_specific', 0, 'link_excerpt', 365, 'public', '2026-08-23');
"""
