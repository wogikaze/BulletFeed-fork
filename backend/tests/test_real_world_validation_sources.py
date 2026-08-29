from __future__ import annotations

from pathlib import Path

from app.evaluation.real_world_validation import (
    SOURCE_FAMILIES,
    capacity_status,
    load_real_world_validation,
)

_V01 = Path(__file__).parent / "gold" / "real_world_validation" / "v01"


def test_first_collection_batch_has_real_https_provenance() -> None:
    corpus = load_real_world_validation(_V01)
    assert len(corpus.sources) >= 21
    assert len(corpus.events) >= 21
    families = {source.source_family for source in corpus.sources}
    assert len(families) >= 6
    assert families <= set(SOURCE_FAMILIES)
    assert {source.language for source in corpus.sources} >= {"en", "ja"}
    for source in corpus.sources:
        assert source.canonical_url.startswith("https://")
        assert source.collected_at
        assert source.raw_evidence
        assert source.static_fetch_ok is True
    status = capacity_status(corpus)
    assert status.meets_targets is False
    js_need = [
        source
        for source in corpus.sources
        if source.static_fetch_ok
        and source.static_normalize_insufficient
        and source.js_render_would_recover
    ]
    assert js_need == []
