from app.services import github_advisory_source
from app.services.github_advisory_source import normalize_github_advisories


def _advisory(summary: str = "Authentication bypass") -> dict:
    return {
        "ghsa_id": "GHSA-abcd-1234-5678",
        "cve_id": "CVE-2026-10001",
        "url": "https://api.github.com/advisories/GHSA-abcd-1234-5678",
        "html_url": "https://github.com/advisories/GHSA-abcd-1234-5678",
        "summary": summary,
        "description": summary,
        "severity": "high",
        "published_at": "2026-08-20T00:00:00Z",
        "updated_at": "2026-08-21T00:00:00Z",
        "vulnerabilities": [
            {
                "package": {"ecosystem": "pip", "name": "example"},
                "vulnerable_version_range": "< 2.0.0",
                "first_patched_version": {"identifier": "2.0.0"},
            }
        ],
    }


def test_normalize_github_advisory_preserves_ghsa_identity_and_provenance() -> None:
    observations = normalize_github_advisories([_advisory()], ecosystem="pip")

    assert len(observations) == 1
    observation = observations[0]
    assert observation.source_type == "github_advisory"
    assert observation.source_key == "pip"
    assert observation.source_observation_id == "GHSA-abcd-1234-5678"
    assert observation.original_url == "https://github.com/advisories/GHSA-abcd-1234-5678"
    assert observation.published_at == "2026-08-20T00:00:00Z"


async def test_crawl_github_advisory_appends_revisions_without_overwrite(database, monkeypatch) -> None:
    responses = [[_advisory()], [_advisory("Authentication bypass; patch available")]]

    async def fake_list(*args, **kwargs):
        del args, kwargs
        return responses.pop(0)

    monkeypatch.setattr(github_advisory_source, "list_global_advisories", fake_list)

    first = await github_advisory_source.crawl_github_advisories(
        object(),
        database,
        ecosystem="pip",
        retrieved_at="2026-08-21T01:00:00Z",
    )
    second = await github_advisory_source.crawl_github_advisories(
        object(),
        database,
        ecosystem="pip",
        retrieved_at="2026-08-21T02:00:00Z",
    )

    assert first[0].source_observation_id == second[0].source_observation_id
    assert first[0].id != second[0].id
    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT source_observation_id, payload_hash, original_url
            FROM observations
            WHERE source_type = 'github_advisory' AND source_key = 'pip'
            ORDER BY retrieved_at
            """
        ).fetchall()
    assert len(rows) == 2
    assert rows[0]["source_observation_id"] == rows[1]["source_observation_id"]
    assert rows[0]["payload_hash"] != rows[1]["payload_hash"]
    assert all(row["original_url"].startswith("https://github.com/advisories/") for row in rows)
