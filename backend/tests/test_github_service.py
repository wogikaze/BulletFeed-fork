import pytest

from app.config import Settings
from app.services import github

_LIST_REPOSITORIES = github.list_repositories


class _Response:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload
        self.headers = {}

    def json(self):
        return self._payload


@pytest.mark.asyncio
async def test_list_repositories_follows_all_pages(monkeypatch) -> None:
    pages: list[int] = []

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            del exc_type, exc, tb

        async def get(self, url, *, headers, params):
            del url, headers
            page = params["page"]
            pages.append(page)
            count = 100 if page == 1 else 1
            return _Response(
                200,
                [
                    {
                        "id": (page - 1) * 100 + index,
                        "full_name": f"acme/repo-{(page - 1) * 100 + index}",
                    }
                    for index in range(count)
                ],
            )

    monkeypatch.setattr(github.httpx, "AsyncClient", lambda **kwargs: _Client())

    repositories = await _LIST_REPOSITORIES(Settings(), "token")

    assert len(repositories) == 101
    assert pages == [1, 2]


@pytest.mark.asyncio
async def test_repository_accessible_treats_private_404_as_revoked(monkeypatch) -> None:
    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            del exc_type, exc, tb

        async def get(self, url, *, headers):
            del url, headers
            return _Response(404, {"message": "Not Found"})

    monkeypatch.setattr(github.httpx, "AsyncClient", lambda **kwargs: _Client())

    result = await github.repository_accessible(Settings(), "acme", "private", "token")

    assert result is None
