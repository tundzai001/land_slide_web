"""HTTP response middleware shared by the application entry point."""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class CharsetMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        content_type = response.headers.get("content-type", "")
        textual = (
            "text/" in content_type
            or "application/javascript" in content_type
            or "application/json" in content_type
        )
        if textual and "charset=" not in content_type.lower():
            response.headers["content-type"] = f"{content_type}; charset=utf-8"
        return response


class VersionedAssetCacheMiddleware(BaseHTTPMiddleware):
    """Keep HTML fresh while caching immutable versioned JS/CSS assets."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        path = request.url.path.lower()
        if path.endswith((".js", ".css")) and request.query_params.get("v"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            if "Pragma" in response.headers:
                del response.headers["Pragma"]
            if "Expires" in response.headers:
                del response.headers["Expires"]
        elif path.endswith((".html", ".js", ".css")):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response


# Compatibility alias for older imports and focused tests.
NoCacheHTMLMiddleware = VersionedAssetCacheMiddleware
