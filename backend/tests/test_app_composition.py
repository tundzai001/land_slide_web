import asyncio
from collections import Counter

from starlette.requests import Request
from starlette.responses import Response

from app.main import app
from app.middleware import CharsetMiddleware, VersionedAssetCacheMiddleware
from app.features.rescue import storage as rescue_storage


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
        ("/api/auth/login", ("POST",)): "app.features.authentication.router",
        ("/api/auth/me", ("GET",)): "app.features.authentication.router",
        ("/api/auth/ws-ticket", ("POST",)): "app.features.authentication.router",
        ("/api/admin/db/stats", ("GET",)): "app.features.database_admin.read_router",
        ("/api/health", ("GET",)): "app.features.health.router",
        ("/ws/updates", ("APIWebSocketRoute",)): "app.features.frontend.websocket",
        ("/api/field/register", ("POST",)): "app.features.field.pi_devices",
        ("/api/public/rescue-requests", ("POST",)): "app.features.rescue.router",
        ("/api/admin/rescue-requests", ("GET",)): "app.features.rescue.router",
        ("/api/admin/gnss/adjustment/start", ("POST",)): "app.features.gnss_adjustment.router",
        ("/api/admin/gnss/adjustment/status", ("GET",)): "app.features.gnss_adjustment.router",
        ("/api/admin/gnss/adjustment/reports/{project_id}/{filename}", ("GET",)): "app.features.data_export.reports.adjustment.router",
        ("/api/admin/gnss/adjustment/reports/{project_code}/{cluster_name}/{path:path}", ("GET",)): "app.features.data_export.reports.adjustment.router",
        ("/api/admin/stations/{station_id}/devices", ("GET",)): "app.features.devices.router",
        ("/api/public/cors-base-stations", ("GET",)): "app.features.projects.cors_stations",
        ("/api/projects", ("GET",)): "app.features.projects.public",
        ("/api/admin/projects", ("GET",)): "app.features.projects.admin",
        ("/api/stations", ("GET",)): "app.features.stations.query_router",
        ("/api/stations/{station_id}/history", ("GET",)): "app.features.stations.query_router",
        ("/api/stations/{station_id}/detail", ("GET",)): "app.features.stations.query_router",
        ("/api/field/provision", ("POST",)): "app.features.field.provisioning_router",
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


def test_root_html_is_always_revalidated():
    middleware = VersionedAssetCacheMiddleware(lambda _scope, _receive, _send: None)

    async def call_next(_request):
        return Response("ok", media_type="text/html")

    response = asyncio.run(middleware.dispatch(_request("/"), call_next))

    assert response.headers["cache-control"] == "no-cache, no-store, must-revalidate"


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
    assert rescue_storage.protected_image_url("/static/uploads/rescue/a.jpg") == (
        "/api/admin/rescue-images/a.jpg"
    )
    assert rescue_storage.resolve_image_path("/static/uploads/rescue/../secret") is None


def test_only_allowlisted_static_directories_are_mounted():
    mounts = {
        route.path: str(getattr(route.app, "directory", ""))
        for route in app.routes
        if hasattr(route, "app") and hasattr(route.app, "directory")
    }
    assert set(mounts) == {"/assets"}
    assert mounts["/assets"].replace("\\", "/").endswith("/frontend/dist")
    assert all("adjustments" not in directory for directory in mounts.values())
    assert all("uploads" not in directory for directory in mounts.values())
