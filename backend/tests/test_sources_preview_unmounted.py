from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.main import app


def _is_sources_preview_path(path: str) -> bool:
    return path == "/v1/sources" or path.startswith("/v1/sources/")


def test_main_app_openapi_has_no_sources_preview_paths() -> None:
    schema = app.openapi()
    leaked = sorted(path for path in schema["paths"] if _is_sources_preview_path(path))
    assert leaked == []


def test_main_app_routes_have_no_sources_preview_paths() -> None:
    leaked = sorted(
        {
            route.path
            for route in app.routes
            if isinstance(route, APIRoute) and _is_sources_preview_path(route.path)
        }
    )
    assert leaked == []


def test_main_app_rejects_sources_preview_http(client: TestClient) -> None:
    assert client.get("/v1/sources/github/releases").status_code == 404
    assert client.post("/v1/sources/osv/query").status_code == 404
