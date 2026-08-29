"""Local-only seed/inspect routes for Android real-backend acceptance.

Mounted only when BULLETFEED_ACCEPTANCE_HARNESS=1. No OAuth, no token echo.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.database import Database
from app.dependencies import get_database
from app.schemas.common import ApiModel
from app.services.feed_projection import FeedProjector
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
            "SELECT COUNT(*) AS count FROM user_claim_exposures WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    return ExposureCountResponse(count=int(row["count"]) if row is not None else 0)
