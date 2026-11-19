"""Verify that production frontend assets are public and source files are not."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.main import app  # noqa: E402


async def get(
    path: str,
    query: str = "",
    extra_headers: tuple[tuple[bytes, bytes], ...] = (),
) -> tuple[int, dict[str, str], bytes]:
    messages: list[dict] = []
    response_complete = asyncio.Event()
    request_sent = False

    async def receive():
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await response_complete.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        await asyncio.sleep(0)
        messages.append(message)
        if message["type"] == "http.response.body" and not message.get("more_body", False):
            response_complete.set()

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": query.encode("ascii"),
        "root_path": "",
        "headers": [(b"host", b"testserver"), *extra_headers],
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
    }
    await app(scope, receive, send)
    start = next(message for message in messages if message["type"] == "http.response.start")
    headers = {
        key.decode("latin-1").lower(): value.decode("latin-1")
        for key, value in start["headers"]
    }
    body = b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    )
    return start["status"], headers, body


CONTRACT_QUERY = "v=contract"


async def verify() -> None:
    for route in ("/", "/map", "/login", "/management"):
        status, headers, body = await get(route)
        assert status == 200, (route, status)
        assert b"/assets/" in body, route
        assert "no-cache" in headers.get("cache-control", ""), (route, headers)

    status, headers, body = await get("/assets/app-runtime.min.js", CONTRACT_QUERY)
    assert status == 200 and body, status
    assert "immutable" in headers.get("cache-control", ""), headers
    assert "javascript" in headers.get("content-type", ""), headers

    status, headers, _ = await get(
        "/assets/map-app.min.js",
        CONTRACT_QUERY,
        ((b"accept-encoding", b"gzip"),),
    )
    assert status == 200, status
    assert headers.get("content-encoding") == "gzip", headers

    status, headers, body = await get("/static/sounds/siren.mp3", CONTRACT_QUERY)
    assert status == 200 and body, status
    assert headers.get("x-content-type-options") == "nosniff", headers

    for source_path in (
        "/js/app-runtime.js",
        "/js/react/station-list.jsx",
        "/js/templates/map-template.js",
        "/css/map/base.css",
        "/static/adjustments/gnss_adjustment_1_1.json",
        "/static/uploads/rescue/evidence.png",
        "/static/sounds/secrets.json",
    ):
        status, _, _ = await get(source_path)
        assert status == 404, (source_path, status)

    for protected_path in (
        "/api/admin/gnss/adjustment/reports/1/gnss_adjustment_1_1.json",
        "/api/admin/rescue-images/evidence.png",
    ):
        status, headers, _ = await get(protected_path)
        assert status == 401, (protected_path, status)
        assert "no-store" in headers.get("cache-control", ""), headers


if __name__ == "__main__":
    asyncio.run(verify())
    print("Frontend HTTP contract verified: dist=200, source paths=404")
