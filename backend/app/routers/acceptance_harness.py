"""Local-only seed/inspect routes for Android real-backend acceptance.

Mounted only when BULLETFEED_ACCEPTANCE_HARNESS=1. No OAuth, no token echo.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.database import Database
from app.dependencies import get_database
from app.schemas.common import ApiModel
from app.services.false_suppression import decide_suppression
from app.services.feed_projection import FeedProjector
from app.services.knowledge_evidence import replay_knowledge_state
from app.services.knowledge_identity import resolve_claim_knowledge_id
from app.services.ledger_projection import LedgerProjector
from app.services.statuspage_pipeline import StatuspagePipeline

router = APIRouter(tags=["acceptance-harness"])


class SeedRequest(ApiModel):
    user_id: str


class SeedResponse(ApiModel):
    event_ids: list[str]
    projected_item_count: int


class ExposureCountResponse(ApiModel):
    count: int


class KnownnessRow(ApiModel):
    claim_id: str
    state: str
    action: str


class KnownnessInspectResponse(ApiModel):
    items: list[KnownnessRow]


def _statuspage_summary() -> dict:
    return {
        "incidents": [
            {
                "id": "inc_android_acceptance",
                "name": "API latency",
                "impact": "major",
                "created_at": "2026-08-22T00:00:00Z",
                "shortlink": "https://stspg.io/inc_android_acceptance",
                "incident_updates": [
                    {
                        "id": "upd_android_acceptance_1",
                        "status": "investigating",
                        "body": "Investigating elevated latency.",
                        "created_at": "2026-08-22T00:00:00Z",
                        "updated_at": "2026-08-22T00:00:00Z",
                        "display_at": "2026-08-22T00:00:00Z",
                    },
                    {
                        "id": "upd_android_acceptance_2",
                        "status": "identified",
                        "body": "Database saturation identified.",
                        "created_at": "2026-08-22T00:10:00Z",
                        "updated_at": "2026-08-22T00:10:00Z",
                        "display_at": "2026-08-22T00:10:00Z",
                    },
                ],
            }
        ]
    }


def _require_user(database: Database, user_id: str) -> None:
    with database.connect() as connection:
        row = connection.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")


@router.post("/__acceptance__/seed-statuspage", response_model=SeedResponse)
def seed_statuspage(
    body: SeedRequest,
    database: Annotated[Database, Depends(get_database)],
) -> SeedResponse:
    _require_user(database, body.user_id)
    result = StatuspagePipeline(database).ingest_summary(
        page_id="abcd1234",
        summary=_statuspage_summary(),
        retrieved_at="2026-08-22T00:11:00Z",
    )
    projector = FeedProjector(database)
    projected = 0
    for event_id in result.event_ids:
        LedgerProjector(database).project_event(event_id)
        projected += len(projector.project_event_for_user(user_id=body.user_id, event_id=event_id))
    return SeedResponse(event_ids=list(result.event_ids), projected_item_count=projected)


@router.get("/__acceptance__/claim-exposures", response_model=ExposureCountResponse)
def claim_exposure_count(
    database: Annotated[Database, Depends(get_database)],
    user_id: Annotated[str, Query(alias="userId")],
) -> ExposureCountResponse:
    _require_user(database, user_id)
    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM user_claim_exposures
            WHERE user_id = ? AND state IN ('displayed', 'read')
            """,
            (user_id,),
        ).fetchone()
    return ExposureCountResponse(count=int(row["count"]) if row is not None else 0)


@router.get("/__acceptance__/source-sync-jobs", response_model=ExposureCountResponse)
def source_sync_job_count(
    database: Annotated[Database, Depends(get_database)],
    user_id: Annotated[str, Query(alias="userId")],
    source_type: Annotated[str | None, Query(alias="sourceType")] = None,
    source_key: Annotated[str | None, Query(alias="sourceKey")] = None,
) -> ExposureCountResponse:
    _require_user(database, user_id)
    with database.connect() as connection:
        if source_type and source_key:
            row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM source_sync_jobs
                WHERE source_type = ? AND source_key = ?
                """,
                (source_type, source_key),
            ).fetchone()
        else:
            row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM source_sync_jobs AS jobs
                JOIN source_sync_subscription_users AS users
                  ON users.source_type = jobs.source_type
                 AND users.source_key = jobs.source_key
                WHERE users.user_id = ?
                """,
                (user_id,),
            ).fetchone()
    return ExposureCountResponse(count=int(row["count"]) if row is not None else 0)


@router.get("/__acceptance__/bootstrap-knownness", response_model=KnownnessInspectResponse)
def bootstrap_knownness(
    database: Annotated[Database, Depends(get_database)],
    user_id: Annotated[str, Query(alias="userId")],
    event_id: Annotated[str | None, Query(alias="eventId")] = None,
) -> KnownnessInspectResponse:
    _require_user(database, user_id)
    with database.connect() as connection:
        if event_id:
            rows = connection.execute(
                """
                SELECT DISTINCT m.claim_id
                FROM delta_claim_map m
                JOIN state_claims c ON c.id = m.claim_id
                WHERE c.event_id = ?
                """,
                (event_id,),
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT DISTINCT m.claim_id
                FROM feed_items f
                JOIN delta_claim_map m ON m.delta_id = f.delta_id
                WHERE f.user_id = ?
                """,
                (user_id,),
            ).fetchall()
        items = []
        for row in rows:
            claim_id = str(row["claim_id"])
            derived = replay_knowledge_state(connection, user_id=user_id, claim_id=claim_id)
            mapped = resolve_claim_knowledge_id(connection, claim_id)
            if mapped is None:
                identity_label, identity_confidence = "uncertain", "none"
            elif mapped.decision == "equivalent":
                identity_label, identity_confidence = "same_target", mapped.confidence
            else:
                identity_label, identity_confidence = "uncertain", mapped.confidence or "none"
            action = decide_suppression(
                knowledge_state=derived.state,
                knowledge_confidence=derived.confidence,
                identity_label=identity_label,
                identity_confidence=identity_confidence,
            ).action
            items.append(KnownnessRow(claim_id=claim_id, state=derived.state, action=action))
    return KnownnessInspectResponse(items=items)
