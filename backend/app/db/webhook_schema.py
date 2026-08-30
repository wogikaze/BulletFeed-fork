WEBHOOK_SCHEMA = """
CREATE TABLE IF NOT EXISTS github_webhook_deliveries (
    delivery_id TEXT PRIMARY KEY,
    event_name TEXT NOT NULL,
    signature_valid INTEGER NOT NULL,
    status TEXT NOT NULL,
    event_count INTEGER NOT NULL DEFAULT 0,
    first_received_at INTEGER NOT NULL,
    last_received_at INTEGER NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_github_webhook_deliveries_last_received
ON github_webhook_deliveries(last_received_at);
"""
