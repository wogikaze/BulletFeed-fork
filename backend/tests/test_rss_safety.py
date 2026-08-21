from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.services.rss import validate_feed_url


@patch("app.services.rss.socket.getaddrinfo")
def test_allowed_public_https_feed(mock_getaddrinfo) -> None:
    mock_getaddrinfo.return_value = [(2, 1, 6, "", ("93.184.216.34", 443))]
    url = "https://news.example.com/feed.xml"
    assert validate_feed_url(url, {"example.com"}) == url


def test_rejects_unlisted_host() -> None:
    with pytest.raises(HTTPException) as exc_info:
        validate_feed_url("https://attacker.example/feed.xml", {"official.example"})
    assert exc_info.value.status_code == 403


@patch("app.services.rss.socket.getaddrinfo")
def test_rejects_private_ip(mock_getaddrinfo) -> None:
    mock_getaddrinfo.return_value = [(2, 1, 6, "", ("127.0.0.1", 443))]
    with pytest.raises(HTTPException) as exc_info:
        validate_feed_url("https://feeds.example.com/feed.xml", {"example.com"})
    assert exc_info.value.status_code == 403
