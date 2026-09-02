from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.evaluation.product_gap_c1_live_discovery import _no_feed_fallback_ok, measure_live_g1
from app.services.source_catalog import SourceKind
from app.services.source_feed_discover import SiteFeedDiscoverResult

GOLD = Path(__file__).parent / "gold" / "product_gap" / "c1"


def _result(*, preferred: str, families: tuple[str, ...]) -> SiteFeedDiscoverResult:
    items = tuple(
        SimpleNamespace(family=family, canonical_url=f"https://example.com/{index}")
        for index, family in enumerate(families)
    )
    return SiteFeedDiscoverResult(
        version="test",
        site_url="https://example.com/",
        canonical_site_url="https://example.com/",
        preferred_family=preferred,
        items=items,
    )


def test_no_feed_fallback_accepts_discovered_rss() -> None:
    assert _no_feed_fallback_ok(
        _result(preferred=SourceKind.RSS_ATOM.value, families=(SourceKind.RSS_ATOM.value,))
    )


def test_no_feed_fallback_accepts_generic_web() -> None:
    assert _no_feed_fallback_ok(
        _result(preferred=SourceKind.GENERIC_WEB.value, families=(SourceKind.GENERIC_WEB.value,))
    )


def test_no_feed_fallback_rejects_empty_discovery() -> None:
    empty = SiteFeedDiscoverResult(
        version="test",
        site_url="https://example.com/",
        canonical_site_url="https://example.com/",
        preferred_family=None,
        items=(),
    )
    assert _no_feed_fallback_ok(empty) is False


def _write_no_feed_gold(directory: Path) -> None:
    directory.mkdir(parents=True)
    (directory / "sources.json").write_text(
        json.dumps(
            [
                {
                    "source_id": "c1_test_web_001",
                    "site_url": "https://kernel.org/",
                    "feed_url": None,
                    "canonical_url": "https://kernel.org/",
                    "topic_id": "linux",
                    "family": "docs_changelog",
                    "language": "en",
                    "authority": "primary",
                    "has_feed": False,
                    "domain": "kernel.org",
                    "registrable_domain": "kernel.org",
                    "policy_status": "eligible",
                    "relevance": "relevant",
                    "curation": "test",
                    "split": "dev",
                }
            ]
        ),
        encoding="utf-8",
    )


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


@pytest.mark.asyncio
async def test_live_g1_counts_rss_as_no_feed_success(monkeypatch, tmp_path: Path) -> None:
    gold = tmp_path / "c1"
    _write_no_feed_gold(gold)

    async def fake_discover(settings, site_url, **kwargs):
        del settings, site_url, kwargs
        return _result(
            preferred=SourceKind.RSS_ATOM.value,
            families=(SourceKind.RSS_ATOM.value,),
        )

    monkeypatch.setattr(
        "app.evaluation.product_gap_c1_live_discovery.discover_feeds_from_site_url",
        fake_discover,
    )
    report = await measure_live_g1(gold, split="dev", delay_seconds=0)
    assert report["rows"][0]["status"] == "ok"
    assert report["metrics"]["no_feed_fallback_rate"] == 1.0
    assert report["status_counts"]["ok"] == 1
