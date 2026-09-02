from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from app.config import Settings
from app.evaluation.product_gap_c1_g5_measurement import (
    _same_public_source,
    measure_live_g5,
)

GOLD_V2 = Path(__file__).parent / "gold" / "product_gap" / "c1" / "v2"


def test_same_public_source_strips_www() -> None:
    assert _same_public_source(
        "https://www.mongodb.com/products/updates/rss",
        "https://mongodb.com/products/updates/rss/",
    )


@pytest.mark.asyncio
async def test_measure_live_g5_records_fetch_and_identity(monkeypatch) -> None:
    async def fake_preview(_settings: Settings, url: str) -> dict:
        if "react.dev" in url:
            return {"source_url": "https://react.dev/rss.xml", "items": [{"title": "x", "link": "https://react.dev/"}]}
        return {"source_url": "https://mongodb.com/products/updates/rss", "items": [{"title": "y", "link": "https://mongodb.com/"}]}

    monkeypatch.setattr("app.evaluation.product_gap_c1_g5_measurement.preview_feed", fake_preview)
    report = await measure_live_g5(GOLD_V2, timeout_seconds=1)
    assert report["production_fetch_measured"] is True
    assert report["identity_measured"] is True
    assert report["shape_bypass_count"] == 0


@pytest.mark.asyncio
async def test_measure_live_g5_does_not_invent_fetch_pass(monkeypatch) -> None:
    async def fake_preview(_settings: Settings, _url: str) -> dict:
        raise HTTPException(status_code=502, detail="RSS source returned HTTP 404")

    monkeypatch.setattr("app.evaluation.product_gap_c1_g5_measurement.preview_feed", fake_preview)
    report = await measure_live_g5(GOLD_V2, timeout_seconds=1)
    assert report["production_fetch_measured"] is False
    assert report["identity_measured"] is False
    assert report["shape_bypass_count"] == 0
