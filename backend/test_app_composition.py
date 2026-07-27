import asyncio
from collections import Counter

from starlette.requests import Request
from starlette.responses import Response

from app.main import app
from app.middleware import CharsetMiddleware, VersionedAssetCacheMiddleware
from app.services import rescue_storage


def _route_key(route):
    original_route = getattr(route, "original_route", route)
    methods = tuple(
        sorted(
            getattr(route, "methods", ())
            or getattr(original_route, "methods", ())
            or (original_route.__class__.__name__,)
        )
    )
    return getattr(route, "path", "") or original_route.path, methods


def _route_endpoint_module(route):
    original_route = getattr(route, "original_route", route)
    endpoint = getattr(route, "endpoint", None) or getattr(original_route, "endpoint", None)
    return getattr(endpoint, "__module__", "")


def _iter_effective_routes(routes):
    for route in routes:
        effective_candidates = getattr(route, "effective_candidates", None)
        if callable(effective_candidates):
            yield from _iter_effective_routes(effective_candidates())
        elif hasattr(route, "path"):
            yield route


def test_application_has_no_duplicate_routes():
    counts = Counter(_route_key(route) for route in _iter_effective_routes(app.routes))
    assert [key for key, count in counts.items() if count > 1] == []


def test_extracted_routes_keep_their_public_contract():
    expected_modules = {
        ("/api/auth/login", ("POST",)): "app.routers.authentication",
        ("/api/auth/me", ("GET",)): "app.routers.authentication",
        ("/api/admin/db/stats", ("GET",)): "app.routers.database_admin",
        ("/api/health", ("GET",)): "app.routers.frontend",
        ("/ws/updates", ("APIWebSocketRoute",)): "app.routers.frontend",
        ("/api/field/register", ("POST",)): "app.routers.field",
        ("/api/public/rescue-requests", ("POST",)): "app.routers.rescue",
        ("/api/admin/rescue-requests", ("GET",)): "app.routers.rescue",
        ("/api/admin/gnss/adjustment/start", ("POST",)): "app.routers.gnss_adjustment",
        ("/api/admin/gnss/adjustment/status", ("GET",)): "app.routers.gnss_adjustment",
        ("/api/admin/stations/{station_id}/devices", ("GET",)): "app.routers.devices",
        ("/api/public/cors-base-stations", ("GET",)): "app.routers.cors_stations",
        ("/api/projects", ("GET",)): "app.routers.projects",
        ("/api/admin/projects", ("GET",)): "app.routers.projects",
        ("/api/stations", ("GET",)): "app.routers.stations",
        ("/api/stations/{station_id}/detail", ("GET",)): "app.routers.stations",
        ("/api/field/provision", ("POST",)): "app.routers.field_provisioning",
    }
    actual = {
        _route_key(route): _route_endpoint_module(route)
        for route in _iter_effective_routes(app.routes)
    }
    for key, module_name in expected_modules.items():
        assert actual.get(key) == module_name


def _request(path: str, query_string: bytes = b"") -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": query_string,
            "headers": [],
            "client": ("test", 123),
            "server": ("test", 80),
        }
    )


def test_versioned_assets_are_immutable_but_unversioned_assets_are_not():
    middleware = VersionedAssetCacheMiddleware(lambda _scope, _receive, _send: None)

    async def call_next(_request):
        return Response("ok", media_type="application/javascript")

    versioned = asyncio.run(
        middleware.dispatch(_request("/static/app.js", b"v=20260722"), call_next)
    )
    unversioned = asyncio.run(
        middleware.dispatch(_request("/static/app.js"), call_next)
    )

    assert versioned.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert unversioned.headers["cache-control"] == "no-cache, no-store, must-revalidate"


def test_charset_is_added_only_once():
    middleware = CharsetMiddleware(lambda _scope, _receive, _send: None)

    async def call_next(_request):
        return Response("ok", media_type="application/json")

    response = asyncio.run(middleware.dispatch(_request("/api/health"), call_next))
    assert response.headers["content-type"].lower().count("charset=") == 1


def test_rescue_metadata_round_trip_and_path_guard():
    packed = rescue_storage.pack_message(
        "Need help", "flood", "Lao Cai", "https://example.test", "/static/uploads/rescue/a.jpg"
    )
    unpacked = rescue_storage.unpack_message(packed)
    assert unpacked["text"] == "Need help"
    assert unpacked["rescue_type"] == "flood"
    assert rescue_storage.resolve_image_path("/static/uploads/rescue/a.jpg").name == "a.jpg"
    assert rescue_storage.resolve_image_path("/static/uploads/rescue/../secret") is None
