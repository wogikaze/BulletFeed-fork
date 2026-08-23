from app.services.json_feed import normalize_json_feed
from app.services.rss_source import normalize_feed_preview
from app.services.timestamps import canonical_timestamp


def test_timestamp_normalization_makes_equivalent_offsets_identical() -> None:
    assert canonical_timestamp("2026-08-21T10:00:00+09:00") == "2026-08-21T01:00:00Z"
    assert canonical_timestamp("Fri, 21 Aug 2026 10:00:00 +0900") == "2026-08-21T01:00:00Z"
    assert canonical_timestamp("2026-08-21T01:00:00Z") == "2026-08-21T01:00:00Z"
    assert canonical_timestamp("2026-08-21 10:00:00") is None
    assert canonical_timestamp("not-a-date") is None


def test_rss_and_json_feed_store_canonical_published_times() -> None:
    rss = normalize_feed_preview(
        {
            "source_url": "https://example.com/feed.xml",
            "items": [
                {
                    "title": "Release",
                    "link": "https://example.com/release",
                    "published": "Fri, 21 Aug 2026 10:00:00 +0900",
                }
            ],
        }
    )
    assert rss[0].published_at == "2026-08-21T01:00:00Z"

    json_feed = normalize_json_feed(
        {
            "version": "https://jsonfeed.org/version/1.1",
            "items": [
                {
                    "id": "release",
                    "url": "https://example.com/release",
                    "date_published": "2026-08-21T10:00:00+09:00",
                }
            ],
        },
        feed_url="https://example.com/feed.json",
    )
    assert json_feed[0].published_at == "2026-08-21T01:00:00Z"
