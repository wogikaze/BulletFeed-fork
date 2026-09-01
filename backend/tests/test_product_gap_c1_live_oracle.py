from __future__ import annotations

from pathlib import Path

import pytest

from app.evaluation import product_gap_c1_live_body as body
from app.evaluation import product_gap_c1_live_oracle as oracle
from app.evaluation.product_gap_c1_g5_measurement import measure_g5_shape

FIXTURES = Path(__file__).parent / "fixtures"
GOLD_V2 = Path(__file__).parent / "gold" / "product_gap" / "c1" / "v2"


def test_independent_oracle_parses_rss_without_feedparser() -> None:
    body = (FIXTURES / "rss" / "g3_oracle_feed.xml").read_bytes()
    entries = oracle._oracle_entries(body)
    assert [entry["title"] for entry in entries] == [
        "Important compiler change",
        "Routine changelog",
        "Security advisory",
    ]
    assert len(oracle._important(entries)) == 2
    atom = b"""
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>Atom update</title>
        <link rel="replies" href="https://example.com/comments"/>
        <link rel="alternate" href="https://example.com/article"/>
      </entry>
    </feed>
    """
    assert oracle._oracle_entries(atom)[0]["link"] == "https://example.com/article"


@pytest.mark.asyncio
async def test_live_g3_is_dev_only_and_records_parity(monkeypatch) -> None:
    body = (FIXTURES / "rss" / "g3_oracle_feed.xml").read_bytes()

    async def fake_fetch(_settings, _url):
        return body, "https://blog.example.com/feed.xml", "application/rss+xml"

    async def fake_preview(_settings, _url):
        return {
            "source_url": "https://blog.example.com/feed.xml",
            "items": [
                {"title": "Important compiler change", "link": "https://blog.example.com/compiler-change"},
                {"title": "Routine changelog", "link": "https://blog.example.com/changelog"},
                {"title": "Security advisory", "link": "https://blog.example.com/advisory"},
            ],
        }

    monkeypatch.setattr(oracle, "_fetch_independent", fake_fetch)
    monkeypatch.setattr(oracle, "preview_feed", fake_preview)
    report = await oracle.measure_live_g3(GOLD_V2, limit=1, delay_seconds=0)
    assert report["live_oracle"] is True
    assert report["sample_complete"] is False
    assert report["metrics"]["raw_entry_recall"] == 1.0
    assert report["metrics"]["important_update_recall"] == 1.0
    assert report["metrics"]["duplicate_item_rate"] == 0.0
    with pytest.raises(ValueError, match="dev-only"):
        await oracle.measure_live_g3(GOLD_V2, split="blind", limit=0, delay_seconds=0)


@pytest.mark.asyncio
async def test_live_g4_records_unmeasured_longitudinal_metrics(monkeypatch) -> None:
    async def fake_preview(_settings, _url):
        return {
            "items": [
                {
                    "title": "Important compiler change",
                    "link": "https://blog.example.com/compiler-change",
                    "summary": "Short teaser.",
                }
            ]
        }

    async def fake_enrich(_settings, item, *, retrieved_at):
        return {
            **item,
            "article_text": "A measured article body.",
            "evidence_locator": "dom:article;off:0-20",
            "article_content_hash": "hash",
            "retrieved_at": retrieved_at,
        }

    monkeypatch.setattr(body, "preview_feed", fake_preview)
    monkeypatch.setattr(body, "enrich_feed_item", fake_enrich)
    report = await body.measure_live_g4(GOLD_V2, max_items=1, delay_seconds=0)
    assert report["metrics"]["body_success"] == 1.0
    assert report["metrics"]["important_body_recall"] == 1.0
    assert report["metrics"]["update_recall"] is None
    assert report["metrics"]["update_precision"] is None
    assert report["metrics"]["article_split"] is None
    assert report["sample_complete"] is False


def test_g5_artifact_keeps_fetch_and_identity_unmeasured() -> None:
    report = measure_g5_shape(GOLD_V2)
    assert report["sample_complete"] is True
    assert report["case_count"] >= 100
    assert report["shape_bypass_count"] == 0
    assert report["production_fetch_measured"] is True
    assert report["identity_measured"] is True
    assert report["live_network_measured"] is False
