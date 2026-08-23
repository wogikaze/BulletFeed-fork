from fastapi.testclient import TestClient

from app.database import Database
from app.security import token_hash
from app.services.dependency_security_pipeline import ingest_sbom_security_events


def _authenticated_user_id(database: Database, auth_headers: dict[str, str]) -> str:
    access_token = auth_headers["Authorization"].removeprefix("Bearer ")
    with database.connect() as connection:
        row = connection.execute(
            "SELECT user_id FROM user_sessions WHERE token_hash = ?",
            (token_hash(access_token),),
        ).fetchone()
    assert row is not None
    return row["user_id"]


def test_real_sbom_osv_finding_populates_security_and_notification_apis(
    client: TestClient,
    auth_headers: dict[str, str],
    database: Database,
) -> None:
    user_id = _authenticated_user_id(database, auth_headers)
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO github_repo_watches (
                user_id, repository_id, full_name, html_url, selected
            ) VALUES (?, '1', 'acme/widget', 'https://github.com/acme/widget', 1)
            """,
            (user_id,),
        )

    ingest_sbom_security_events(
        database,
        owner="acme",
        repository="widget",
        sbom_response={
            "sbom": {
                "spdxVersion": "SPDX-2.3",
                "packages": [
                    {
                        "name": "requests",
                        "versionInfo": "2.0.0",
                        "externalRefs": [
                            {
                                "referenceType": "purl",
                                "referenceLocator": "pkg:pypi/requests@2.0.0",
                            }
                        ],
                    }
                ],
            }
        },
        batch_results=(
            (
                {
                    "id": "GHSA-real-1234",
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
                },
            ),
        ),
        retrieved_at="2026-08-20T10:02:00Z",
    )

    alerts = client.get("/v1/me/security/alerts", headers=auth_headers)
    assert alerts.status_code == 200
    alert_items = alerts.json()["items"]
    assert len(alert_items) == 1
    alert = alert_items[0]
    assert alert["advisoryId"] == "GHSA-real-1234"
    assert alert["cve"] == "CVE-2026-1234"
    assert alert["severity"] == "high"
    assert alert["repository"]["fullName"] == "acme/widget"
    assert alert["package"]["currentVersion"] == "2.0.0"
    assert alert["package"]["fixedVersion"] == "2.32.4"

    patched = client.patch(
        f"/v1/me/security/alerts/{alert['id']}",
        headers=auth_headers,
        json={"status": "in_progress"},
    )
    assert patched.status_code == 200
    assert patched.json()["status"] == "in_progress"

    notifications = client.get(
        "/v1/me/notifications",
        headers=auth_headers,
        params={"status": "unread"},
    )
    assert notifications.status_code == 200
    notification_items = notifications.json()["items"]
    assert len(notification_items) == 1
    notification = notification_items[0]
    assert notification["category"] == "security"
    assert notification["target"]["type"] == "security_alert"
    assert notification["target"]["id"] == alert["id"]

    marked = client.patch(
        f"/v1/me/notifications/{notification['id']}",
        headers=auth_headers,
        json={"read": True},
    )
    assert marked.status_code == 200
    assert marked.json()["read"] is True

    ingest_sbom_security_events(
        database,
        owner="acme",
        repository="widget",
        sbom_response={
            "sbom": {
                "spdxVersion": "SPDX-2.3",
                "packages": [
                    {
                        "name": "requests",
                        "versionInfo": "2.0.0",
                        "externalRefs": [
                            {
                                "referenceType": "purl",
                                "referenceLocator": "pkg:pypi/requests@2.0.0",
                            }
                        ],
                    }
                ],
            }
        },
        batch_results=(({
            "id": "GHSA-real-1234",
            "aliases": ["CVE-2026-1234"],
            "published": "2026-08-20T10:00:00Z",
            "modified": "2026-08-20T10:01:00Z",
            "summary": "requests 2.0.0 is vulnerable.",
            "database_specific": {"severity": "HIGH"},
        },),),
        retrieved_at="2026-08-20T10:03:00Z",
    )

    assert client.get(
        f"/v1/me/security/alerts/{alert['id']}",
        headers=auth_headers,
    ).json()["status"] == "in_progress"
    all_notifications = client.get("/v1/me/notifications", headers=auth_headers).json()["items"]
    assert all_notifications[0]["read"] is True
