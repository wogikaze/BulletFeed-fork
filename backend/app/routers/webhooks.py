from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from app.config import Settings, get_settings
from app.database import Database
from app.dependencies import get_database
from app.observability import record
from app.services.github_release_pipeline import ingest_github_release_events
from app.services.github_webhook import release_from_webhook_payload, verify_github_webhook_signature

router = APIRouter(prefix="/v1/webhooks", tags=["webhooks"])


@router.post("/github")
async def github_webhook(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    database: Annotated[Database, Depends(get_database)],
    x_hub_signature_256: Annotated[str | None, Header()] = None,
    x_github_event: Annotated[str | None, Header()] = None,
    x_github_delivery: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    event_name = (x_github_event or "").strip()
    secret = settings.github_webhook_secret.get_secret_value()
    if not secret:
        record(
            "webhook",
            source_type="github_release",
            github_event=event_name,
            delivery_id=x_github_delivery,
            accepted=False,
            reason="secret_not_configured",
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GitHub webhook secret is not configured",
        )
    body = await request.body()
    if not verify_github_webhook_signature(
        secret=secret,
        body=body,
        signature_header=x_hub_signature_256,
    ):
        record(
            "webhook",
            source_type="github_release",
            github_event=event_name,
            delivery_id=x_github_delivery,
            accepted=False,
            signature_valid=False,
            reason="invalid_signature",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature",
        )

    if event_name != "release":
        record(
            "webhook",
            source_type="github_release",
            github_event=event_name,
            delivery_id=x_github_delivery,
            accepted=True,
            signature_valid=True,
            ingested=False,
            ignored=True,
        )
        return {"accepted": True, "ignored": True}

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        record(
            "webhook",
            source_type="github_release",
            github_event=event_name,
            delivery_id=x_github_delivery,
            accepted=False,
            signature_valid=True,
            reason="invalid_json",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook payload is not valid JSON",
        ) from exc

    extracted = release_from_webhook_payload(payload)
    if extracted is None:
        record(
            "webhook",
            source_type="github_release",
            github_event=event_name,
            delivery_id=x_github_delivery,
            accepted=False,
            signature_valid=True,
            reason="incomplete_release_payload",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Release webhook payload is incomplete",
        )
    owner, repository, release = extracted
    retrieved_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    result = ingest_github_release_events(
        database,
        owner=owner,
        repository=repository,
        releases=[release],
        retrieved_at=retrieved_at,
    )
    record(
        "webhook",
        source_type="github_release",
        github_event=event_name,
        delivery_id=x_github_delivery,
        accepted=True,
        signature_valid=True,
        ingested=True,
        event_count=len(result.event_ids),
    )
    return {
        "accepted": True,
        "ignored": False,
        "deliveryId": x_github_delivery,
        "eventIds": list(result.event_ids),
    }
