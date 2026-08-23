SYNC_SCHEMA = """
CREATE TABLE IF NOT EXISTS source_sync_jobs (
    source_type TEXT NOT NULL,
    repository_full_name TEXT NOT NULL,
    next_run_at INTEGER NOT NULL,
    lease_until INTEGER NOT NULL DEFAULT 0,
    lease_token TEXT,
    failure_count INTEGER NOT NULL DEFAULT 0,
    last_attempt_at INTEGER,
    last_success_at INTEGER,
    last_error TEXT,
    PRIMARY KEY(source_type, repository_full_name)
);

CREATE INDEX IF NOT EXISTS idx_source_sync_jobs_due
ON source_sync_jobs(next_run_at, lease_until);
"""
