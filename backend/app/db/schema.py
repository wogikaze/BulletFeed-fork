PUBLIC_API_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    created_at INTEGER NOT NULL,
    onboarding_completed INTEGER NOT NULL DEFAULT 0,
    github_connected INTEGER NOT NULL DEFAULT 0,
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
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS feedback (
    id TEXT PRIMARY KEY,
    feed_item_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    type TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    FOREIGN KEY(feed_item_id) REFERENCES feed_items(id),
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
"""
