from __future__ import annotations

from dataclasses import dataclass

from app.database import Database


@dataclass(frozen=True)
class WebhookHealth:
    tracked_deliveries: int
    accepted_deliveries: int
    ignored_deliveries: int
    signature_failures: int
    last_delivery_id: str | None
    last_status: str | None
    last_received_at: int | None

    def as_public_dict(self) -> dict[str, object]:
        return {
            "trackedDeliveries": self.tracked_deliveries,
            "acceptedDeliveries": self.accepted_deliveries,
            "ignoredDeliveries": self.ignored_deliveries,
            "signatureFailures": self.signature_failures,
            "lastDeliveryId": self.last_delivery_id,
            "lastStatus": self.last_status,
            "lastReceivedAt": self.last_received_at,
        }


def record_webhook_delivery(
    database: Database,
    *,
    delivery_id: str | None,
    event_name: str,
    signature_valid: bool,
    status: str,
    event_count: int = 0,
    received_at: int,
) -> None:
    """Persist delivery metadata only; request payloads and secrets never enter this table."""
    if not delivery_id:
        return
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO github_webhook_deliveries (
                delivery_id, event_name, signature_valid, status, event_count,
                first_received_at, last_received_at, attempt_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(delivery_id) DO UPDATE SET
                event_name = excluded.event_name,
                signature_valid = excluded.signature_valid,
                status = excluded.status,
                event_count = excluded.event_count,
                last_received_at = excluded.last_received_at,
                attempt_count = github_webhook_deliveries.attempt_count + 1
            """,
            (
                delivery_id,
                event_name,
                int(signature_valid),
                status,
                event_count,
                received_at,
                received_at,
            ),
        )


def summarize_webhook_health(database: Database) -> WebhookHealth:
    with database.connect() as connection:
        totals = connection.execute(
            """
            SELECT
                COUNT(*) AS tracked,
                COALESCE(SUM(status IN ('ingested', 'ignored')), 0) AS accepted,
                COALESCE(SUM(status = 'ignored'), 0) AS ignored,
                COALESCE(SUM(status = 'rejected_invalid_signature'), 0) AS signature_failures
            FROM github_webhook_deliveries
            """
        ).fetchone()
        last = connection.execute(
            """
            SELECT delivery_id, status, last_received_at
            FROM github_webhook_deliveries
            ORDER BY last_received_at DESC, delivery_id DESC
            LIMIT 1
            """
        ).fetchone()
    return WebhookHealth(
        tracked_deliveries=int(totals["tracked"]),
        accepted_deliveries=int(totals["accepted"]),
        ignored_deliveries=int(totals["ignored"]),
        signature_failures=int(totals["signature_failures"]),
        last_delivery_id=str(last["delivery_id"]) if last is not None else None,
        last_status=str(last["status"]) if last is not None else None,
        last_received_at=int(last["last_received_at"]) if last is not None else None,
    )
