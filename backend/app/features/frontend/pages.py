"""Frontend document and public-asset routes."""

from __future__ import annotations

import re
from pathlib import Path
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.responses import JSONResponse
from ...config import settings

FRONTEND_DIR = Path(__file__).resolve().parents[4] / "frontend" / "dist"
PUBLIC_SOUND_DIR = Path(__file__).resolve().parents[3] / "static" / "sounds"
PUBLIC_SOUND_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,79}\.mp3$")

router = APIRouter()

def _frontend_document(file_name: str, *, private: bool = False):
    file_path = FRONTEND_DIR / file_name
    if not file_path.exists():
        return JSONResponse(status_code=503, content={"error": "Frontend not found"})
    noindex = private or settings.ENVIRONMENT.lower() != "production"
    headers = {"X-Robots-Tag": "noindex, noarchive"} if noindex else {}
    return FileResponse(file_path, media_type="text/html; charset=utf-8", headers=headers)


@router.get("/static/sounds/{file_name}")
def get_public_sound(file_name: str):
    """Serve only known-safe MP3 filenames from the public sound directory."""
    if PUBLIC_SOUND_NAME.fullmatch(file_name) is None:
        return JSONResponse(status_code=404, content={"detail": "Sound not found"})
    sound_path = (PUBLIC_SOUND_DIR / file_name).resolve()
    if sound_path.parent != PUBLIC_SOUND_DIR.resolve() or not sound_path.is_file():
        return JSONResponse(status_code=404, content={"detail": "Sound not found"})
    return FileResponse(
        sound_path,
        media_type="audio/mpeg",
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.get("/")
def read_root(request: Request):
    legacy_view = (request.query_params.get("view") or "").lower()
    if legacy_view in {"admin", "management"}:
        return RedirectResponse(url="/management", status_code=307)
    if legacy_view in {"map", "login"}:
        return RedirectResponse(url=f"/{legacy_view}", status_code=307)
    return _frontend_document("index.html")


@router.get("/about")
def read_about():
    return _frontend_document("about.html")


@router.get("/management")
@router.get("/management.html")
@router.get("/admin")
@router.get("/admin.html")
def read_app():
    return _frontend_document("app.html", private=True)


@router.get("/map")
def read_map():
    return _frontend_document("map.html")


@router.get("/login")
def read_login():
    return _frontend_document("app.html", private=True)


@router.get("/robots.txt")
def robots_txt():
    site_url = settings.PUBLIC_SITE_URL.rstrip("/")
    if settings.ENVIRONMENT.lower() != "production":
        return PlainTextResponse("User-agent: *\nDisallow: /\n")
    return PlainTextResponse(
        f"User-agent: *\nDisallow: /api/\nDisallow: /ws/\nSitemap: {site_url}/sitemap.xml\n"
    )


@router.get("/sitemap.xml")
def sitemap_xml():
    if settings.ENVIRONMENT.lower() != "production":
        return Response(status_code=404)
    site_url = settings.PUBLIC_SITE_URL.rstrip("/")
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f'<url><loc>{site_url}/</loc></url>'
        f'<url><loc>{site_url}/map</loc></url>'
        f'<url><loc>{site_url}/about</loc></url>'
        '</urlset>'
    )
    return Response(content=xml, media_type="application/xml")


@router.get("/favicon.ico", include_in_schema=False)
def favicon_ico():
    file_path = FRONTEND_DIR / "aitogy.png"
    if file_path.exists():
        return FileResponse(file_path, media_type="image/png")
    return Response(status_code=404)


@router.get("/img/aitogy.png", include_in_schema=False)
def aitogy_logo():
    file_path = FRONTEND_DIR / "aitogy.png"
    if file_path.exists():
        return FileResponse(file_path, media_type="image/png")
    return Response(status_code=404)
