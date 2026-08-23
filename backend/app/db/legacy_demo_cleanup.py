from __future__ import annotations

import sqlite3


# These identifiers were used only by the original local demo workspace. Older
# databases can still contain the fixtures even though new sessions are no longer
# seeded with them. Repository/topic reprojection can otherwise make those stale
# feed rows visible again.
_DEMO_EVENT_IDS = (
    "workers-runtime",
    "kotlin-release",
    "openai-pricing",
    "android-security",
)
_DEMO_SECURITY_ALERT_IDS = (
    "vuln-next-auth",
    "vuln-undici",
    "vuln-compose-preview",
)
_DEMO_NOTIFICATION_IDS = (
    "notification-next-auth",
    "notification-workers-runtime",
    "notification-kotlin-release",
)


def remove_legacy_demo_workspace(connection: sqlite3.Connection) -> None:
    """Remove obsolete demo projections without touching real ingested data."""

    # Delivery-dependent rows must be removed before their demo feed items
    # because the original schema does not use cascading foreign keys.
    connection.execute(
        "DELETE FROM user_claim_exposures WHERE delivery_id IN ("
        "SELECT id FROM deliveries WHERE feed_item_id IN ("
        "SELECT id FROM feed_items WHERE event_id IN (?, ?, ?, ?)))",
        _DEMO_EVENT_IDS,
    )
    connection.execute(
        "DELETE FROM exposures WHERE delivery_id IN ("
        "SELECT id FROM deliveries WHERE feed_item_id IN ("
        "SELECT id FROM feed_items WHERE event_id IN (?, ?, ?, ?)))",
        _DEMO_EVENT_IDS,
    )
    connection.execute(
        "DELETE FROM feedback WHERE feed_item_id IN "
        "(SELECT id FROM feed_items WHERE event_id IN (?, ?, ?, ?))",
        _DEMO_EVENT_IDS,
    )
    connection.execute(
        "DELETE FROM deliveries WHERE feed_item_id IN "
        "(SELECT id FROM feed_items WHERE event_id IN (?, ?, ?, ?))",
        _DEMO_EVENT_IDS,
    )
    connection.execute(
        "DELETE FROM feed_items WHERE event_id IN (?, ?, ?, ?)",
        _DEMO_EVENT_IDS,
    )
    connection.execute(
        "DELETE FROM event_follows WHERE event_id IN (?, ?, ?, ?)",
        _DEMO_EVENT_IDS,
    )
    connection.execute(
        "DELETE FROM notifications WHERE id IN (?, ?, ?)",
        _DEMO_NOTIFICATION_IDS,
    )
    connection.execute(
        "DELETE FROM security_alerts WHERE id IN (?, ?, ?)",
        _DEMO_SECURITY_ALERT_IDS,
    )
