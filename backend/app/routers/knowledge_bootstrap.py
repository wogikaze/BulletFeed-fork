from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.database import Database
from app.dependencies import get_database, require_user
from app.errors import unprocessable
from app.schemas.knowledge_bootstrap import (
    BootstrapCheckpointItem,
    BootstrapCheckpointRequest,
    BootstrapCheckpointResponse,
    BootstrapClaimRequest,
    BootstrapClaimsResponse,
    BootstrapEvidenceItem,
    BootstrapSummaryResponse,
)
from app.services.knowledge_bootstrap import (
    POLICY_VERSION,
    UnknownBootstrapClaimError,
    UnknownBootstrapSubjectError,
    inspect_bootstrap,
    record_current_state_checkpoint,
    record_explicit_bootstrap,
    reset_bootstrap_knowledge,
)

router = APIRouter(prefix="/v1", tags=["knowledge-bootstrap"])


def _as_of_ts(value: str | None) -> int | None:
    if value is None or not value.strip():
        return None
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except ValueError as exc:
        raise unprocessable("asOf must be an ISO-8601 timestamp") from exc


def _evidence_item(row) -> BootstrapEvidenceItem:
    return BootstrapEvidenceItem(
        id=row.id,
        kind=row.kind,
        provenance=row.provenance,
        confidence=row.confidence,
        source_id=row.source_id,
        claim_id=row.claim_id,
        event_id=row.event_id,
        created_at=row.created_at,
    )


@router.get("/me/knowledge/bootstrap", response_model=BootstrapSummaryResponse)
def get_bootstrap(
    user: Annotated[dict, Depends(require_user)],
    database: Annotated[Database, Depends(get_database)],
) -> BootstrapSummaryResponse:
    with database.connect() as connection:
        summary = inspect_bootstrap(connection, user_id=user["user_id"])
    return BootstrapSummaryResponse(
        version=POLICY_VERSION,
        explicit_claim_ids=list(summary.explicit_claim_ids),
        inferred_claim_ids=list(summary.inferred_claim_ids),
        checkpoints=[
            BootstrapCheckpointItem(
                subject_kind=item.subject_kind,
                subject_id=item.subject_id,
                as_of=item.as_of,
                catch_up=item.catch_up,
                claim_ids=list(item.claim_ids),
            )
            for item in summary.checkpoints
        ],
        evidence=[_evidence_item(row) for row in summary.evidence],
    )


@router.post(
    "/me/knowledge/bootstrap/claims",
    response_model=BootstrapClaimsResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_bootstrap_claims(
    body: BootstrapClaimRequest,
    user: Annotated[dict, Depends(require_user)],
    database: Annotated[Database, Depends(get_database)],
) -> BootstrapClaimsResponse:
    try:
        with database.connect() as connection:
            session_id, claim_ids = record_explicit_bootstrap(
                connection,
                user_id=user["user_id"],
                claim_ids=body.claim_ids,
                session_id=body.session_id,
            )
            connection.commit()
    except UnknownBootstrapClaimError as exc:
        raise unprocessable(f"unknown claim: {exc}") from exc
    return BootstrapClaimsResponse(
        version=POLICY_VERSION,
        session_id=session_id,
        claim_ids=list(claim_ids),
    )


@router.put(
    "/me/knowledge/bootstrap/checkpoint",
    response_model=BootstrapCheckpointResponse,
)
def put_bootstrap_checkpoint(
    body: BootstrapCheckpointRequest,
    user: Annotated[dict, Depends(require_user)],
    database: Annotated[Database, Depends(get_database)],
) -> BootstrapCheckpointResponse:
    try:
        with database.connect() as connection:
            checkpoint = record_current_state_checkpoint(
                connection,
                user_id=user["user_id"],
                subject_kind=body.subject_kind,
                subject_id=body.subject_id,
                catch_up=body.catch_up,
                as_of=_as_of_ts(body.as_of),
                topic_name=body.subject_id if body.subject_kind == "topic" else None,
            )
            connection.commit()
    except UnknownBootstrapSubjectError as exc:
        raise unprocessable(f"unsupported subject: {exc}") from exc
    return BootstrapCheckpointResponse(
        version=POLICY_VERSION,
        subject_kind=checkpoint.subject_kind,
        subject_id=checkpoint.subject_id,
        as_of=checkpoint.as_of,
        catch_up=checkpoint.catch_up,
        claim_ids=list(checkpoint.claim_ids),
    )


@router.delete("/me/knowledge/bootstrap", status_code=status.HTTP_204_NO_CONTENT)
def delete_bootstrap(
    user: Annotated[dict, Depends(require_user)],
    database: Annotated[Database, Depends(get_database)],
) -> Response:
    with database.connect() as connection:
        reset_bootstrap_knowledge(connection, user_id=user["user_id"])
        connection.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
