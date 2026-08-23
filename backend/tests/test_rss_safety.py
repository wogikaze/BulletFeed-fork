from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.config import Settings
from app.services.rss import _download, validate_feed_url


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


class _FakeNetworkStream:
    def __init__(self, peer: str) -> None:
        self.peer = peer

    def get_extra_info(self, name: str):
        return (self.peer, 443) if name == "server_addr" else None


class _FakeResponse:
    def __init__(self, *, peer: str, headers: dict[str, str], chunks: list[bytes]) -> None:
        self.status_code = 200
        self.headers = headers
        self.extensions = {"network_stream": _FakeNetworkStream(peer)}
        self._chunks = chunks

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def aiter_raw(self):
        for chunk in self._chunks:
            yield chunk


class _FakeClient:
    def __init__(self, response: _FakeResponse) -> None:
        self.response = response
        self.request_headers: dict[str, str] | None = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    def stream(self, method: str, url: str, **kwargs):
        del method, url
        self.request_headers = kwargs["headers"]
        return self.response


@pytest.mark.asyncio
@patch("app.services.rss.socket.getaddrinfo")
async def test_download_rejects_dns_rebinding_peer(mock_getaddrinfo, monkeypatch) -> None:
    mock_getaddrinfo.return_value = [(2, 1, 6, "", ("93.184.216.34", 443))]
    fake = _FakeClient(
        _FakeResponse(
            peer="127.0.0.1",
            headers={"content-type": "application/rss+xml"},
            chunks=[b"feed"],
        )
    )
    monkeypatch.setattr("app.services.rss.httpx.AsyncClient", lambda **kwargs: fake)

    settings = Settings(rss_allowed_hosts="example.com")
    with pytest.raises(HTTPException) as exc_info:
        await _download(settings, "https://feeds.example.com/feed.xml")
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
@patch("app.services.rss.socket.getaddrinfo")
async def test_download_rejects_compressed_response_and_requests_identity(
    mock_getaddrinfo,
    monkeypatch,
) -> None:
    mock_getaddrinfo.return_value = [(2, 1, 6, "", ("93.184.216.34", 443))]
    fake = _FakeClient(
        _FakeResponse(
            peer="93.184.216.34",
            headers={
                "content-type": "application/rss+xml",
                "content-encoding": "gzip",
            },
            chunks=[b"compressed"],
        )
    )
    monkeypatch.setattr("app.services.rss.httpx.AsyncClient", lambda **kwargs: fake)

    settings = Settings(rss_allowed_hosts="example.com")
    with pytest.raises(HTTPException) as exc_info:
        await _download(settings, "https://feeds.example.com/feed.xml")
    assert exc_info.value.status_code == 415
    assert fake.request_headers is not None
    assert fake.request_headers["Accept-Encoding"] == "identity"


@pytest.mark.asyncio
@patch("app.services.rss.socket.getaddrinfo")
async def test_download_bounds_raw_response_before_extending_buffer(
    mock_getaddrinfo,
    monkeypatch,
) -> None:
    mock_getaddrinfo.return_value = [(2, 1, 6, "", ("93.184.216.34", 443))]
    fake = _FakeClient(
        _FakeResponse(
            peer="93.184.216.34",
            headers={"content-type": "application/rss+xml"},
            chunks=[b"123", b"456"],
        )
    )
    monkeypatch.setattr("app.services.rss.httpx.AsyncClient", lambda **kwargs: fake)

    settings = Settings(rss_allowed_hosts="example.com", max_response_bytes=4)
    with pytest.raises(HTTPException) as exc_info:
        await _download(settings, "https://feeds.example.com/feed.xml")
    assert exc_info.value.status_code == 413
