"""Browser cookie transport; API clients retain explicitly supplied bearer tokens."""
import hashlib
import hmac
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, Response

from .config import settings


def cookie_names():
    prefix = "__Host-" if settings.ENVIRONMENT.lower() == "production" else ""
    return prefix + "monitoring_session", prefix + "monitoring_csrf"


def csrf_token(jti):
    return hmac.new(settings.SECRET_KEY.encode(), ("browser-csrf:" + jti).encode(), hashlib.sha256).hexdigest()


def require_origin(request: Request):
    origin = request.headers.get("origin")
    allowed = set(settings.allowed_cors_origins)
    site = urlsplit(settings.PUBLIC_SITE_URL)
    allowed.add(f"{site.scheme}://{site.netloc}")
    if origin not in allowed:
        raise HTTPException(403, "Request origin is not allowed")


def _extract_and_validate_claims(header: str | None, cookie: str | None, decode_access_token, jwt_error_cls) -> tuple[str, dict]:
    if header is not None:
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise jwt_error_cls("Invalid authorization header")
        claims = decode_access_token(token)
        if claims.get("transport") == "cookie":
            raise jwt_error_cls("Cookie credentials cannot be used as bearer tokens")
        return token, claims
    token = cookie
    claims = decode_access_token(token)
    if claims.get("transport") != "cookie":
        raise jwt_error_cls("Invalid cookie credential")
    return token, claims


def _verify_csrf_if_cookie_mutation(request: Request, is_cookie_auth: bool, jti: str):
    if is_cookie_auth and request.method not in {"GET", "HEAD", "OPTIONS"}:
        require_origin(request)
        supplied = request.headers.get("x-csrf-token", "")
        if not hmac.compare_digest(supplied, csrf_token(jti)):
            raise HTTPException(403, "Session verification failed. Reload and try again.")


def request_token(request: Request, *, required=True):
    from .auth import decode_access_token, JWTError
    header = request.headers.get("authorization")
    session_name, _ = cookie_names()
    cookie = request.cookies.get(session_name)
    if header is None and not cookie:
        if not required:
            return None
        raise HTTPException(401, "Authentication required", headers={"WWW-Authenticate": "Bearer"})
    try:
        token, claims = _extract_and_validate_claims(header, cookie, decode_access_token, JWTError)
    except JWTError:
        raise HTTPException(401, "Invalid credentials", headers={"WWW-Authenticate": "Bearer"}) from None

    _verify_csrf_if_cookie_mutation(request, header is None, claims["jti"])
    return token


def set_cookies(response: Response, request: Request, token, jti, max_age=None):
    session_name, csrf_name = cookie_names()
    secure = settings.ENVIRONMENT.lower() == "production" or request.url.scheme == "https"
    options = {"path": "/", "secure": secure, "samesite": "lax", "max_age": max_age}
    response.set_cookie(session_name, token, httponly=True, **options)
    response.set_cookie(csrf_name, csrf_token(jti), httponly=False, **options)
    response.headers["Cache-Control"] = "private, no-store"


def set_csrf_cookie(response: Response, request: Request, jti: str):
    _, csrf_name = cookie_names()
    secure = settings.ENVIRONMENT.lower() == "production" or request.url.scheme == "https"
    options = {"path": "/", "secure": secure, "samesite": "lax", "httponly": False}
    response.set_cookie(csrf_name, csrf_token(jti), **options)


def clear_cookies(response: Response):
    for name in cookie_names():
        response.delete_cookie(name, path="/", secure=settings.ENVIRONMENT.lower() == "production", samesite="lax")
