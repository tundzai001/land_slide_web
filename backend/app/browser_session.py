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
    allowed = set(settings.cors_origins)
    site = urlsplit(settings.PUBLIC_SITE_URL)
    allowed.add(f"{site.scheme}://{site.netloc}")
    if origin not in allowed:
        raise HTTPException(403, "Request origin is not allowed")


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
        if header is not None:
            scheme, _, token = header.partition(" ")
            if scheme.lower() != "bearer" or not token:
                raise JWTError("Invalid authorization header")
            claims = decode_access_token(token)
            if claims.get("transport") == "cookie":
                raise JWTError("Cookie credentials cannot be used as bearer tokens")
        else:
            token = cookie
            claims = decode_access_token(token)
            if claims.get("transport") != "cookie":
                raise JWTError("Invalid cookie credential")
    except JWTError:
        raise HTTPException(401, "Invalid credentials", headers={"WWW-Authenticate": "Bearer"}) from None
    if header is None and request.method not in {"GET", "HEAD", "OPTIONS"}:
        require_origin(request)
        supplied = request.headers.get("x-csrf-token", "")
        if not hmac.compare_digest(supplied, csrf_token(claims["jti"])):
            raise HTTPException(403, "Session verification failed. Reload and try again.")
    return token


def set_cookies(response: Response, request: Request, token, jti, max_age=None):
    session_name, csrf_name = cookie_names()
    secure = settings.ENVIRONMENT.lower() == "production" or request.url.scheme == "https"
    options = dict(path="/", secure=secure, samesite="lax", max_age=max_age)
    response.set_cookie(session_name, token, httponly=True, **options)
    response.set_cookie(csrf_name, csrf_token(jti), httponly=False, **options)
    response.headers["Cache-Control"] = "private, no-store"


def clear_cookies(response: Response):
    for name in cookie_names():
        response.delete_cookie(name, path="/", secure=settings.ENVIRONMENT.lower() == "production", samesite="lax")
