import json
from pathlib import Path

from app.database import Database
from app.services.dependency_security_pipeline import ingest_sbom_security_events


def _sbom(version: str) -> dict:
    return {
        "sbom": {
            "spdxVersion": "SPDX-2.3",
            "packages": [
                {
                    "name": "requests",
                    "versionInfo": version,
                    "externalRefs": [
                        {
                            "referenceType": "purl",
                            "referenceLocator": f"pkg:pypi/requests@{version}",
                        }
                    ],
                }
            ],
        }
    }


def _vulnerability() -> dict:
    return {
        "id": "GHSA-test-1234",
        "aliases": ["CVE-2026-1234"],
        "published": "2026-08-20T10:00:00Z",
        "modified": "2026-08-20T10:01:00Z",
        "summary": "requests 2.0.0 is vulnerable.",
        "database_specific": {"severity": "HIGH"},
        "affected": [
            {
                "ranges": [
                    {
                        "type": "ECOSYSTEM",
                        "events": [
                            {"introduced": "0"},
                            {"fixed": "2.32.4"},
                        ],
                    }
                ]
            }
        ],
    }


def _database_with_watch(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES ('user_1', 0)")
        connection.execute(
            """
            INSERT INTO github_repo_watches (
                user_id, repository_id, full_name, html_url, selected, private
            ) VALUES ('user_1', '1', 'acme/widget', 'https://github.com/acme/widget', 1, 0)
            """
        )
    return database


def test_sbom_osv_finding_reaches_direct_user_surfaces_with_two_evidence_sources(
    tmp_path: Path,
) -> None:
    database = _database_with_watch(tmp_path)
    result = ingest_sbom_security_events(
        database,
        owner="acme",
        repository="widget",
        sbom_response=_sbom("2.0.0"),
        batch_results=((_vulnerability(),),),
        retrieved_at="2026-08-20T10:02:00Z",
    )
    event_id = result.event_ids[0]

    with database.connect() as connection:
        sources = connection.execute(
            "SELECT * FROM event_sources WHERE event_id = ? ORDER BY kind",
            (event_id,),
        ).fetchall()
        feed = connection.execute(
            "SELECT * FROM feed_items WHERE user_id = 'user_1' AND event_id = ?",
            (event_id,),
        ).fetchone()
        alert = connection.execute(
            "SELECT * FROM security_alerts WHERE user_id = 'user_1'",
        ).fetchone()
        notification = connection.execute(
            "SELECT * FROM notifications WHERE user_id = 'user_1'",
        ).fetchone()

    assert result.package_count == 1
    assert {row["kind"] for row in sources} == {"github_sbom", "osv"}
    assert feed["relation_level"] == "direct"
    assert json.loads(feed["matched_repos_json"]) == [
        {
            "id": "1",
            "name": "acme/widget",
            "url": "https://github.com/acme/widget",
        }
    ]
    assert alert["advisory_id"] == "GHSA-test-1234"
    assert alert["cve"] == "CVE-2026-1234"
    assert alert["fixed_version"] == "2.32.4"
    assert alert["severity"] == "high"
    assert alert["status"] == "open"
    assert notification["category"] == "security"
    assert notification["target_id"] == alert["id"]


def test_dependency_upgrade_reconciles_same_event_and_alert_to_resolved(tmp_path: Path) -> None:
    database = _database_with_watch(tmp_path)
    first = ingest_sbom_security_events(
        database,
        owner="acme",
        repository="widget",
        sbom_response=_sbom("2.0.0"),
        batch_results=((_vulnerability(),),),
        retrieved_at="2026-08-20T10:02:00Z",
    )
    second = ingest_sbom_security_events(
        database,
        owner="acme",
        repository="widget",
        sbom_response=_sbom("2.32.4"),
        batch_results=((),),
        retrieved_at="2026-08-21T10:02:00Z",
    )

    event_id = first.event_ids[0]
    assert second.event_ids == (event_id,)
    with database.connect() as connection:
        event = connection.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        deltas = connection.execute(
            "SELECT type FROM deltas WHERE event_id = ? AND active = 1 ORDER BY occurred_at, id",
            (event_id,),
        ).fetchall()
        alert = connection.execute(
            "SELECT * FROM security_alerts WHERE user_id = 'user_1' AND repository_full_name = 'acme/widget'"
        ).fetchone()
        notifications = connection.execute(
            "SELECT * FROM notifications WHERE user_id = 'user_1' ORDER BY occurred_at"
        ).fetchall()

    assert event["current_phase"] == "fixed"
    assert [row["type"] for row in deltas] == ["new_fact", "state_update"]
    assert alert["status"] == "resolved"
    assert alert["current_version"] == "2.32.4"
    assert len(notifications) == 2
    assert notifications[-1]["title"] == "Security resolved: requests"
