from __future__ import annotations

from dataclasses import dataclass

from app.database import Database


@dataclass(frozen=True)
class ProvenanceAuditReport:
    displayed_claim_count: int
    complete_chain_count: int
    broken_chain_count: int

    @property
    def coverage(self) -> float:
        if self.displayed_claim_count == 0:
            return 1.0
        return self.complete_chain_count / self.displayed_claim_count


def audit_displayed_provenance(database: Database) -> ProvenanceAuditReport:
    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT DISTINCT f.id AS feed_item_id, m.claim_id
            FROM feed_items f
            JOIN delta_claim_map m ON m.delta_id = f.delta_id
            ORDER BY f.id
            """
        ).fetchall()

        complete = 0
        for row in rows:
            chain = connection.execute(
                """
                SELECT 1
                FROM claim_evidence ce
                JOIN observations o ON o.id = ce.observation_id
                JOIN event_source_claim_map scm
                    ON scm.claim_id = ce.claim_id AND scm.evidence_id = ce.id
                JOIN event_sources es ON es.id = scm.source_id
                WHERE ce.claim_id = ?
                  AND ce.original_url <> ''
                  AND es.url = ce.original_url
                  AND es.evidence = ce.evidence_text
                LIMIT 1
                """,
                (row["claim_id"],),
            ).fetchone()
            if chain is not None:
                complete += 1

    total = len(rows)
    return ProvenanceAuditReport(
        displayed_claim_count=total,
        complete_chain_count=complete,
        broken_chain_count=total - complete,
    )
