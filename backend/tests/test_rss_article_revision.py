from pathlib import Path

from app.database import Database
from app.services.rss_article_enrichment import (
    enrich_html_bytes,
    format_claim_evidence,
    is_summary_only,
)
from app.services.rss_pipeline import ingest_feed_events
from app.services.web_snapshots import RobotsDecision

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "rss"


def _robots() -> RobotsDecision:
    return RobotsDecision(
        source_url="https://blog.example.com/compiler-change",
        robots_url=None,
        allowed=True,
        reason="fixture",
        retrieved_at="2026-08-01T00:00:00Z",
    )


def _enrich(name: str):
    return enrich_html_bytes(
        url="https://blog.example.com/compiler-change",
        body=(FIXTURES / name).read_bytes(),
        robots=_robots(),
        retrieved_at="2026-08-01T00:00:00Z",
    )


def _article_preview(enrichment, *, updated: str, summary: str = "Short teaser.") -> dict:
    return {
        "title": "Acme Engineering",
        "source_url": "https://blog.example.com/feed.xml",
        "items": [
            {
                "title": "Important compiler change",
                "link": "https://blog.example.com/compiler-change",
                "published": "2026-08-01T00:00:00Z",
                "updated": updated,
                "summary": summary,
                "article_text": enrichment.article_text,
                "evidence_locator": enrichment.evidence_locator,
                "article_content_hash": enrichment.article_content_hash,
            }
        ],
    }


def test_long_feed_body_skips_article_fetch() -> None:
    long_body = "x" * 281
    assert is_summary_only("Short teaser.", feed_body=long_body) is False
    assert is_summary_only("Short teaser.", feed_body="") is True


def test_long_summary_without_feed_body_still_needs_article_fetch() -> None:
    assert is_summary_only("s" * 400, feed_body="") is True
    assert is_summary_only("s" * 400, feed_body="x" * 281) is False


def test_boilerplate_only_html_keeps_main_text_hash() -> None:
    original = _enrich("article_with_boilerplate.html")
    chrome = _enrich("article_boilerplate_only.html")
    assert original.reason == "enriched"
    assert chrome.reason == "enriched"
    assert original.article_text == chrome.article_text
    assert original.article_content_hash == chrome.article_content_hash
    assert "Site chrome" not in original.article_text
    assert "cookie banner" not in chrome.article_text


def test_boilerplate_html_change_does_not_surface_a_new_delta(tmp_path: Path) -> None:
    database = Database(tmp_path / "boilerplate.db")
    database.initialize()
    original = _enrich("article_with_boilerplate.html")
    chrome = _enrich("article_boilerplate_only.html")
    first = ingest_feed_events(
        database,
        preview=_article_preview(original, updated="2026-08-01T00:01:00Z"),
        retrieved_at="2026-08-01T00:02:00Z",
    )
    second = ingest_feed_events(
        database,
        preview=_article_preview(chrome, updated="2026-08-01T12:00:00Z"),
        retrieved_at="2026-08-01T12:01:00Z",
    )
    assert first.event_ids == second.event_ids
    event_id = first.event_ids[0]
    with database.connect() as connection:
        deltas = connection.execute(
            "SELECT type FROM deltas WHERE event_id = ? ORDER BY occurred_at, id",
            (event_id,),
        ).fetchall()
        relations = [
            row["relation_type"]
            for row in connection.execute(
                """
                SELECT relation_type FROM claim_relations
                WHERE event_id = ?
                ORDER BY occurred_at, id
                """,
                (event_id,),
            )
        ]
    assert "NEW_FACT" in relations
    assert "NON_NOVEL" in relations
    assert [row["type"] for row in deltas] == ["new_fact"]


def test_article_body_update_is_same_event_detail_delta(tmp_path: Path) -> None:
    database = Database(tmp_path / "body-update.db")
    database.initialize()
    original = _enrich("article_with_boilerplate.html")
    updated = _enrich("article_body_updated.html")
    assert original.article_content_hash != updated.article_content_hash
    assert "rollback path" in updated.article_text
    first = ingest_feed_events(
        database,
        preview=_article_preview(original, updated="2026-08-01T00:01:00Z"),
        retrieved_at="2026-08-01T00:02:00Z",
    )
    second = ingest_feed_events(
        database,
        preview=_article_preview(updated, updated="2026-08-02T00:00:00Z"),
        retrieved_at="2026-08-02T00:01:00Z",
    )
    assert first.event_ids == second.event_ids
    event_id = first.event_ids[0]
    with database.connect() as connection:
        deltas = connection.execute(
            "SELECT type, summary FROM deltas WHERE event_id = ? AND active = 1 ORDER BY occurred_at, id",
            (event_id,),
        ).fetchall()
        evidence = connection.execute(
            "SELECT evidence FROM event_sources WHERE event_id = ? ORDER BY retrieved_at, id",
            (event_id,),
        ).fetchall()
    assert [row["type"] for row in deltas] == ["new_fact", "detail"]
    assert any("rollback path" in row["summary"] for row in deltas)
    assert any("根拠位置: " in row["evidence"] for row in evidence)
    assert any("unsafe transform" in row["evidence"] for row in evidence)


def test_format_claim_evidence_keeps_body_before_locator() -> None:
    formatted = format_claim_evidence(
        detail="The mid-end now rejects the unsafe transform.",
        evidence_locator="dom:article>p;off:0-40",
    )
    assert formatted.startswith("The mid-end")
    assert "根拠位置: dom:article>p;off:0-40" in formatted
