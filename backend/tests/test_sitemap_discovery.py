from pathlib import Path

from app.database import Database
from app.services.sitemap_discovery import parse_sitemap, record_sitemap_candidates

SITEMAP = b'''<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://docs.acme.example/releases/widget-2</loc>
    <lastmod>2026-08-20T10:00:00Z</lastmod>
  </url>
  <url>
    <loc>https://docs.acme.example/changelog</loc>
  </url>
</urlset>
'''

INDEX = b'''<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap>
    <loc>https://docs.acme.example/sitemap-releases.xml</loc>
    <lastmod>2026-08-21</lastmod>
  </sitemap>
</sitemapindex>
'''


def test_parse_sitemap_separates_urlset_and_nested_sitemap_hints() -> None:
    urls = parse_sitemap(SITEMAP)
    nested = parse_sitemap(INDEX)

    assert [(item.url, item.last_modified, item.is_sitemap) for item in urls] == [
        ("https://docs.acme.example/releases/widget-2", "2026-08-20T10:00:00Z", False),
        ("https://docs.acme.example/changelog", None, False),
    ]
    assert nested[0].is_sitemap is True


def test_sitemap_candidates_are_not_observations_and_refresh_last_seen(tmp_path: Path) -> None:
    database = Database(tmp_path / "test.db")
    database.initialize()

    first = record_sitemap_candidates(
        database,
        sitemap_url="https://docs.acme.example/sitemap.xml",
        xml_bytes=SITEMAP,
        seen_at="2026-08-20T10:05:00Z",
    )
    second = record_sitemap_candidates(
        database,
        sitemap_url="https://docs.acme.example/sitemap.xml",
        xml_bytes=SITEMAP,
        seen_at="2026-08-20T11:05:00Z",
    )

    assert [item.id for item in first] == [item.id for item in second]
    assert all(item.discovery_method == "sitemap" for item in second)
    assert second[0].publisher_timestamp == "2026-08-20T10:00:00Z"
    assert second[0].last_seen_at == "2026-08-20T11:05:00Z"
    with database.connect() as connection:
        observation_count = connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        candidate_count = connection.execute("SELECT COUNT(*) FROM discovery_candidates").fetchone()[0]
    assert observation_count == 0
    assert candidate_count == 2
