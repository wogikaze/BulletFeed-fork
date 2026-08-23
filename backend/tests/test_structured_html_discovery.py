from pathlib import Path

from app.database import Database
from app.services.structured_html_discovery import (
    extract_structured_page_hint,
    record_structured_html_candidate,
)

HTML = '''
<html>
<head>
  <link rel="canonical" href="/releases/widget-2">
  <script type="application/ld+json">
  {
    "@context": "https://schema.org",
    "@type": "TechArticle",
    "url": "https://docs.acme.example/releases/widget-2?tracking=1",
    "datePublished": "2026-08-20T10:00:00Z",
    "dateModified": "2026-08-21T09:00:00Z"
  }
  </script>
</head>
<body>Changed page body that is not a semantic claim yet.</body>
</html>
'''


def test_structured_html_prefers_canonical_and_extracts_publisher_timestamps() -> None:
    hint = extract_structured_page_hint(
        HTML,
        page_url="https://docs.acme.example/releases/widget-2?utm=x",
    )

    assert hint.canonical_url == "https://docs.acme.example/releases/widget-2"
    assert hint.schema_type == "TechArticle"
    assert hint.date_published == "2026-08-20T10:00:00Z"
    assert hint.date_modified == "2026-08-21T09:00:00Z"


def test_structured_html_hint_is_candidate_not_observation(tmp_path: Path) -> None:
    database = Database(tmp_path / "test.db")
    database.initialize()

    candidate = record_structured_html_candidate(
        database,
        page_url="https://docs.acme.example/releases/widget-2?utm=x",
        html_text=HTML,
        seen_at="2026-08-21T09:01:00Z",
    )

    assert candidate.discovery_method == "structured_html"
    assert candidate.target_url == "https://docs.acme.example/releases/widget-2"
    assert candidate.publisher_timestamp == "2026-08-21T09:00:00Z"
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM discovery_candidates").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 0
