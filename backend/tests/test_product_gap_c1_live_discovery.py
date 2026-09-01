from __future__ import annotations

from pathlib import Path

import pytest

from app.evaluation.product_gap_c1_live_discovery import measure_live_g1

GOLD = Path(__file__).parent / "gold" / "product_gap" / "c1"


@pytest.mark.asyncio
async def test_live_g1_does_not_touch_blind_without_final_opt_in() -> None:
    with pytest.raises(ValueError, match="blind measurement requires"):
        await measure_live_g1(GOLD, split="blind", limit=1, delay_seconds=0)


@pytest.mark.asyncio
async def test_live_g1_zero_limit_performs_no_network() -> None:
    report = await measure_live_g1(GOLD, split="dev", limit=0, delay_seconds=0)
    assert report["split"] == "dev"
    assert report["blind_final"] is False
    assert report["selected_sources"] == 0
    assert report["rows"] == []
