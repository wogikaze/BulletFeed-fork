from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.services.crawler_identity import (
    RELEASE_CRAWLER_USER_AGENT,
    validate_crawler_user_agent,
)
from app.services.web_snapshots import DEFAULT_USER_AGENT


def test_release_default_is_not_local_prototype() -> None:
    assert "local-prototype" not in RELEASE_CRAWLER_USER_AGENT
    assert RELEASE_CRAWLER_USER_AGENT.startswith("BulletFeed/")
    assert DEFAULT_USER_AGENT == RELEASE_CRAWLER_USER_AGENT
    assert Settings().crawler_user_agent == RELEASE_CRAWLER_USER_AGENT


def test_empty_or_unsafe_user_agent_is_rejected() -> None:
    with pytest.raises(ValueError, match="required"):
        validate_crawler_user_agent("   ")
    with pytest.raises(ValueError, match="control"):
        validate_crawler_user_agent("BulletFeed/1.0\n(+evil)")
    with pytest.raises(ValueError, match="product token"):
        validate_crawler_user_agent("(+no-token)")
    with pytest.raises(ValidationError):
        Settings(crawler_user_agent="")


def test_settings_override_is_validated(monkeypatch) -> None:
    monkeypatch.setenv("BULLETFEED_CRAWLER_USER_AGENT", "BulletFeed-test/9 (+https://example.test)")
    from app.config import get_settings

    get_settings.cache_clear()
    assert get_settings().crawler_user_agent == "BulletFeed-test/9 (+https://example.test)"
    get_settings.cache_clear()
