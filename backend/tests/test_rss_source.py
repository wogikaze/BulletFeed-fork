from app.services.rss_source import normalize_feed_preview


def test_normalize_feed_preview_uses_entry_link_as_stable_identity() -> None:
    preview = {
        "source_url": "https://example.com/feed.xml",
        "items": [
            {
                "title": "Release notes",
                "link": "https://example.com/releases/2",
                "published": "2026-08-20T00:00:00Z",
                "summary": "changes",
            }
        ],
    }

    observations = normalize_feed_preview(preview)

    assert len(observations) == 1
    observation = observations[0]
    assert observation.source_type == "rss_atom"
    assert observation.source_key == "https://example.com/feed.xml"
    assert observation.source_observation_id == "https://example.com/releases/2"
    assert observation.original_url == "https://example.com/releases/2"
