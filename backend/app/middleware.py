"""HTTP response middleware shared by the application entry point."""
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class CharsetMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        started_at = time.perf_counter()
        request_id = uuid.uuid4().hex
        response = await call_next(request)
        content_type = response.headers.get("content-type", "")
        textual = (
            "text/" in content_type
            or "application/javascript" in content_type
            or "application/json" in content_type
        )
        if textual and "charset=" not in content_type.lower():
            response.headers["content-type"] = f"{content_type}; charset=utf-8"
        response.headers["X-Request-ID"] = request_id
        response.headers["Server-Timing"] = f"app;dur={(time.perf_counter() - started_at) * 1000:.1f}"
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), payment=(), usb=()",
        )
        response.headers.setdefault("Content-Security-Policy", "base-uri 'self'; object-src 'none'; frame-ancestors 'none'; form-action 'self'")
        if request.url.scheme == "https":
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return response


class VersionedAssetCacheMiddleware(BaseHTTPMiddleware):
    """Keep HTML fresh while caching immutable versioned JS/CSS assets."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        path = request.url.path.lower()
        versioned_extensions = (".js", ".jsx", ".css", ".png", ".jpg", ".jpeg", ".webp", ".svg", ".woff", ".woff2", ".mp3")
        html_routes = {
            "/", "/about", "/map", "/login", "/management", "/management.html",
            "/admin", "/admin.html",
        }
        if path.startswith("/api/") or request.headers.get("authorization"):
            response.headers["Cache-Control"] = "private, no-store, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        elif path.endswith(versioned_extensions) and request.query_params.get("v"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            if "Pragma" in response.headers:
                del response.headers["Pragma"]
            if "Expires" in response.headers:
                del response.headers["Expires"]
        elif path in html_routes or path.endswith((".html", ".js", ".css")):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response


# Compatibility alias for older imports and focused tests.
NoCacheHTMLMiddleware = VersionedAssetCacheMiddleware
