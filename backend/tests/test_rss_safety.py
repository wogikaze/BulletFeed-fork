import gzip
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
    def __init__(
        self,
        *,
        peer: str,
        headers: dict[str, str],
        chunks: list[bytes],
        status_code: int = 200,
    ) -> None:
        self.status_code = status_code
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


class _MappedClient:
    def __init__(self, routes: dict[str, _FakeResponse]) -> None:
        self.routes = routes
        self.requested: list[str] = []
        self.request_headers: dict[str, str] | None = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    def stream(self, method: str, url: str, **kwargs):
        del method
        self.requested.append(url)
        self.request_headers = kwargs["headers"]
        return self.routes[url]


_XML_FEED = b'<?xml version="1.0"?><rss version="2.0"><channel><title>t</title></channel></rss>'


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
async def test_download_rejects_invalid_gzip_and_requests_identity(
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
async def test_download_decodes_bounded_gzip_xml(
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
            chunks=[gzip.compress(_XML_FEED)],
        )
    )
    monkeypatch.setattr("app.services.rss.httpx.AsyncClient", lambda **kwargs: fake)
    settings = Settings(rss_allowed_hosts="example.com")
    body, final_url = await _download(settings, "https://feeds.example.com/feed.xml")
    assert body.startswith(b"<?xml")
    assert final_url == "https://feeds.example.com/feed.xml"
    assert fake.request_headers is not None
    assert fake.request_headers["Accept-Encoding"] == "identity"


@pytest.mark.asyncio
@patch("app.services.rss.socket.getaddrinfo")
async def test_download_sniffs_octet_stream_xml(
    mock_getaddrinfo,
    monkeypatch,
) -> None:
    mock_getaddrinfo.return_value = [(2, 1, 6, "", ("93.184.216.34", 443))]
    fake = _FakeClient(
        _FakeResponse(
            peer="93.184.216.34",
            headers={"content-type": "application/octet-stream"},
            chunks=[_XML_FEED],
        )
    )
    monkeypatch.setattr("app.services.rss.httpx.AsyncClient", lambda **kwargs: fake)
    body, _final_url = await _download(
        Settings(rss_allowed_hosts="example.com"),
        "https://feeds.example.com/feed.xml",
    )
    assert body.startswith(b"<?xml")


@pytest.mark.asyncio
@patch("app.services.rss.socket.getaddrinfo")
async def test_download_follows_https_redirect_off_allowlist_host(
    mock_getaddrinfo,
    monkeypatch,
) -> None:
    mock_getaddrinfo.return_value = [(2, 1, 6, "", ("93.184.216.34", 443))]
    fake = _MappedClient(
        {
            "https://feeds.example.com/feed.xml": _FakeResponse(
                peer="93.184.216.34",
                status_code=301,
                headers={"location": "https://cdn.other.example/feed.xml"},
                chunks=[],
            ),
            "https://cdn.other.example/feed.xml": _FakeResponse(
                peer="93.184.216.34",
                headers={"content-type": "application/rss+xml"},
                chunks=[_XML_FEED],
            ),
        }
    )
    monkeypatch.setattr("app.services.rss.httpx.AsyncClient", lambda **kwargs: fake)
    body, final_url = await _download(
        Settings(rss_allowed_hosts="example.com"),
        "https://feeds.example.com/feed.xml",
    )
    assert body.startswith(b"<?xml")
    assert final_url == "https://cdn.other.example/feed.xml"


@pytest.mark.asyncio
@patch("app.services.rss.socket.getaddrinfo")
async def test_download_upgrades_http_redirect_location_to_https(
    mock_getaddrinfo,
    monkeypatch,
) -> None:
    mock_getaddrinfo.return_value = [(2, 1, 6, "", ("93.184.216.34", 443))]
    fake = _MappedClient(
        {
            "https://security.example.com/feeds/posts/default": _FakeResponse(
                peer="93.184.216.34",
                status_code=302,
                headers={"location": "http://feeds.cdn.example/GoogleOnlineSecurityBlog"},
                chunks=[],
            ),
            "https://feeds.cdn.example/GoogleOnlineSecurityBlog": _FakeResponse(
                peer="93.184.216.34",
                headers={"content-type": "application/rss+xml"},
                chunks=[_XML_FEED],
            ),
        }
    )
    monkeypatch.setattr("app.services.rss.httpx.AsyncClient", lambda **kwargs: fake)
    body, final_url = await _download(
        Settings(rss_allowed_hosts="example.com"),
        "https://security.example.com/feeds/posts/default",
    )
    assert body.startswith(b"<?xml")
    assert final_url == "https://feeds.cdn.example/GoogleOnlineSecurityBlog"
    assert fake.requested == [
        "https://security.example.com/feeds/posts/default",
        "https://feeds.cdn.example/GoogleOnlineSecurityBlog",
    ]

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

    settings = Settings(rss_allowed_hosts="example.com", max_feed_response_bytes=4)
    with pytest.raises(HTTPException) as exc_info:
        await _download(settings, "https://feeds.example.com/feed.xml")
    assert exc_info.value.status_code == 413
