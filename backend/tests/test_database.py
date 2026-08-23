import secrets
import time
from pathlib import Path

from cryptography.fernet import Fernet

from app.database import Database
from app.db.seed import seed_catalog, seed_user_workspace
from app.security import TokenCipher


def test_initialize_seeds_only_non_demo_catalog_data(tmp_path: Path) -> None:
    database = Database(tmp_path / "test.db")
    database.initialize()

    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM topic_catalog").fetchone()[0] > 0
        assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM deltas").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM event_sources").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM event_timeline").fetchone()[0] == 0


def test_initialize_removes_legacy_demo_surfaces_but_preserves_real_data(tmp_path: Path) -> None:
    database = Database(tmp_path / "legacy.db")
    database.initialize()
    _create_user(database, "user-1")

    with database.connect() as connection:
        seed_catalog(connection)
        seed_user_workspace(connection, "user-1")
        demo_feed_item_id = "fi_user-1_delta_workers_identified"
        connection.execute(
            "INSERT INTO deliveries (id, feed_item_id, user_id, created_at) VALUES (?, ?, ?, ?)",
            ("delivery-demo", demo_feed_item_id, "user-1", "2026-08-23T00:00:00Z"),
        )
        connection.execute(
            "INSERT INTO exposures (delivery_id, user_id, displayed_at, created_at) VALUES (?, ?, ?, ?)",
            ("delivery-demo", "user-1", "2026-08-23T00:00:00Z", 1),
        )
        connection.execute(
            "INSERT INTO feedback (id, feed_item_id, user_id, type, created_at) VALUES (?, ?, ?, ?, ?)",
            ("feedback-demo", demo_feed_item_id, "user-1", "important", 1),
        )
        connection.execute(
            """
            INSERT INTO security_alerts (
                id, user_id, advisory_id, title, summary, severity, status,
                repository_full_name, package_name, current_version,
                dependency_type, detected_at, source, evidence, recommendation
            ) VALUES (
                'alert-real', 'user-1', 'GHSA-real', 'Real alert', 'Real summary',
                'high', 'open', 'acme/widget', 'requests', '2.0.0', 'direct',
                '2026-08-23T00:00:00Z', 'OSV + GitHub SBOM', 'Real evidence',
                'Upgrade requests'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO notifications (
                id, user_id, title, summary, category, priority, occurred_at,
                target_type, target_id, read
            ) VALUES (
                'notification-real', 'user-1', 'Real notification', 'Real summary',
                'security', 'high', '2026-08-23T00:00:00Z',
                'security_alert', 'alert-real', 0
            )
            """
        )

    # Starting a newer backend against an existing database performs the
    # targeted cleanup migration.
    database.initialize()

    with database.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM feed_items WHERE event_id IN "
            "('workers-runtime', 'kotlin-release', 'openai-pricing', 'android-security')"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM deliveries WHERE id = 'delivery-demo'"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM exposures WHERE delivery_id = 'delivery-demo'"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM feedback WHERE id = 'feedback-demo'"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM security_alerts WHERE id LIKE 'vuln-%'"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM notifications WHERE id LIKE 'notification-%' "
            "AND id != 'notification-real'"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT advisory_id FROM security_alerts WHERE id = 'alert-real'"
        ).fetchone()[0] == "GHSA-real"
        assert connection.execute(
            "SELECT target_id FROM notifications WHERE id = 'notification-real'"
        ).fetchone()[0] == "alert-real"


def _create_user(database: Database, user_id: str) -> None:
    with database.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES (?, ?)", (user_id, int(time.time())))
        connection.execute(
            """
            INSERT INTO profiles (user_id, occupation, interests_json, region, updated_at)
            VALUES (?, '', '[]', '', ?)
            """,
            (user_id, int(time.time())),
        )


def test_oauth_flow_and_session_lifecycle(tmp_path: Path) -> None:
    database = Database(tmp_path / "test.db")
    database.initialize()
    cipher = TokenCipher(Fernet.generate_key().decode())
    _create_user(database, "user-1")

    state = secrets.token_urlsafe(32)
    poll_token = secrets.token_urlsafe(32)
    database.create_oauth_flow(
        flow_id="flow-1",
        user_id="user-1",
        state=state,
        poll_token=poll_token,
        encrypted_verifier=cipher.encrypt("verifier"),
        expires_at=int(time.time()) + 600,
    )

    flow = database.claim_oauth_flow(state)
    assert flow is not None
    assert cipher.decrypt(flow["pkce_verifier_encrypted"]) == "verifier"

    now = int(time.time())
    app_token = secrets.token_urlsafe(48)
    refresh_token = secrets.token_urlsafe(64)
    canonical_user_id = database.complete_oauth_flow(
        flow_id="flow-1",
        user_id="user-1",
        github_user={"id": 123, "login": "octocat", "avatar_url": "https://example.com/avatar"},
        encrypted_github_token=cipher.encrypt("github-token-example"),
        github_token_expires_at=now + 3600,
        app_access_token=app_token,
        encrypted_app_access_token=cipher.encrypt(app_token),
        refresh_token=refresh_token,
        encrypted_refresh_token=cipher.encrypt(refresh_token),
        app_session_expires_at=now + 3600,
        user_session_expires_at=now + 3600,
        refresh_expires_at=now + 86400,
    )
    assert canonical_user_id == "user-1"

    result = database.get_oauth_status("flow-1", poll_token, cipher)
    assert result is not None
    assert result["status"] == "connected"
    assert result["app_access_token"] == app_token
    assert result["refresh_token"] == refresh_token

    session = database.get_session(app_token, cipher)
    assert session is not None
    assert session["github_user_id"] == 123
    assert session["github_token"].endswith("example")


def test_reauthorization_revokes_older_legacy_session(tmp_path: Path) -> None:
    database = Database(tmp_path / "test.db")
    database.initialize()
    cipher = TokenCipher(Fernet.generate_key().decode())
    _create_user(database, "user-1")
    expires_at = int(time.time()) + 3600

    first_token = secrets.token_urlsafe(48)
    first_refresh = secrets.token_urlsafe(64)
    database.complete_oauth_flow(
        flow_id="first-flow",
        user_id="user-1",
        github_user={"id": 123, "login": "octocat"},
        encrypted_github_token=cipher.encrypt("github-token-old"),
        github_token_expires_at=expires_at,
        app_access_token=first_token,
        encrypted_app_access_token=cipher.encrypt(first_token),
        refresh_token=first_refresh,
        encrypted_refresh_token=cipher.encrypt(first_refresh),
        app_session_expires_at=expires_at,
        user_session_expires_at=expires_at,
        refresh_expires_at=expires_at + 86400,
    )
    assert database.get_session(first_token, cipher) is not None

    second_token = secrets.token_urlsafe(48)
    second_refresh = secrets.token_urlsafe(64)
    database.complete_oauth_flow(
        flow_id="second-flow",
        user_id="user-1",
        github_user={"id": 123, "login": "octocat"},
        encrypted_github_token=cipher.encrypt("github-token-new"),
        github_token_expires_at=expires_at,
        app_access_token=second_token,
        encrypted_app_access_token=cipher.encrypt(second_token),
        refresh_token=second_refresh,
        encrypted_refresh_token=cipher.encrypt(second_refresh),
        app_session_expires_at=expires_at,
        user_session_expires_at=expires_at,
        refresh_expires_at=expires_at + 86400,
    )

    assert database.get_session(first_token, cipher) is None
    current = database.get_session(second_token, cipher)
    assert current is not None
    assert current["github_token"] == "github-token-new"
