from __future__ import annotations

from pathlib import Path

from app.evaluation.real_world_validation import (
    SOURCE_FAMILIES,
    capacity_status,
    load_real_world_validation,
)

_V01 = Path(__file__).parent / "gold" / "real_world_validation" / "v01"

_DROPPED_INDEX_URLS = {
    "https://www.githubstatus.com/history",
    "https://github.blog/changelog/",
    "https://docs.python.org/3/whatsnew/3.12.html",
    "https://www.cloudflarestatus.com/history",
    "https://www.jsonfeed.org/version/1.1/",
    "https://www.ipa.go.jp/security/",
    "https://blog.cloudflare.com/rss/",
    "https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/410",
}


def test_real_events_are_individual_updates_with_fetch_artifacts() -> None:
    corpus = load_real_world_validation(_V01)
    real_events = corpus.real_events()
    assert len(real_events) >= 500
    assert all(event.record_kind == "event_update" for event in real_events)
    assert all(event.occurred_at != "2024-08-01T00:00:00Z" for event in real_events)
    assert all(not event.occurred_at or event.occurred_at_provenance for event in real_events)
    event_pages = [source for source in corpus.sources if source.source_role == "event_page"]
    assert len(event_pages) == len(real_events)
    families = {source.source_family for source in event_pages}
    assert families <= set(SOURCE_FAMILIES)
    assert {source.canonical_url for source in corpus.sources}.isdisjoint(_DROPPED_INDEX_URLS)
    for source in event_pages:
        assert source.canonical_url.startswith("https://")
        assert source.fetch.fetch_kind == "live_https"
        assert source.fetch.http_status == 200
        assert source.evidence_text
        artifact = _V01 / source.fetch.artifact_relpath
        assert artifact.is_file()
        assert source.evidence_text in artifact.read_text(encoding="utf-8")
    fixtures = [event for event in corpus.events if event.record_kind == "contract_fixture"]
    assert len(fixtures) == 3
    assert all(event.is_real_event is False for event in fixtures)
    assert all(event.occurred_at is None for event in fixtures)
    status = capacity_status(corpus)
    assert status.real_event_count >= 500
    assert status.authoritative_endpoint_count >= 120
    js_need = [
        source
        for source in corpus.sources
        if source.static_fetch_ok
        and source.static_normalize_insufficient
        and source.js_render_would_recover
    ]
    assert js_need == []
