"""Encoding and image-storage helpers for rescue requests."""
import base64
import binascii
import hashlib
import json
import re
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, UploadFile

RESCUE_META_PREFIX = "__RESCUE_META_V1__"
RESCUE_IMAGE_DIR = Path(__file__).resolve().parents[3] / "static" / "uploads" / "rescue"
RESCUE_IMAGE_URL_PREFIX = "/api/admin/rescue-images/"
LEGACY_RESCUE_IMAGE_URL_PREFIX = "/static/uploads/rescue/"
MAX_RESCUE_IMAGE_BYTES = 400 * 1024
IMAGE_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
IMAGE_MIME_BY_EXTENSION = {
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
SAFE_IMAGE_FILE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def _validate_image(mime_type: str, image_bytes: bytes) -> str:
    normalized_mime = (mime_type or "").lower()
    extension = IMAGE_EXTENSIONS.get(normalized_mime)
    if not extension:
        raise HTTPException(status_code=400, detail="Unsupported image type")
    if len(image_bytes) > MAX_RESCUE_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail="Image too large")
    signatures_valid = {
        ".jpg": image_bytes.startswith(b"\xff\xd8\xff"),
        ".png": image_bytes.startswith(b"\x89PNG\r\n\x1a\n"),
        ".webp": (
            len(image_bytes) >= 12
            and image_bytes.startswith(b"RIFF")
            and image_bytes[8:12] == b"WEBP"
        ),
    }
    if not signatures_valid.get(extension, False):
        raise HTTPException(status_code=400, detail="Image content does not match its type")
    return extension


def persist_data_url(image_data_url: Optional[str]) -> Optional[str]:
    raw = (image_data_url or "").strip()
    if not raw:
        return None
    if not raw.startswith("data:image/"):
        raise HTTPException(status_code=400, detail="Invalid image format")

    header, separator, encoded = raw.partition(",")
    if not separator:
        raise HTTPException(status_code=400, detail="Invalid image payload")
    mime_type = header.split(";", 1)[0].removeprefix("data:").lower()
    try:
        image_bytes = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid image encoding") from exc

    extension = _validate_image(mime_type, image_bytes)
    RESCUE_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    file_name = f"{hashlib.sha1(image_bytes).hexdigest()}{extension}"  # nosec B324
    file_path = RESCUE_IMAGE_DIR / file_name
    if not file_path.exists():
        file_path.write_bytes(image_bytes)
    return f"{RESCUE_IMAGE_URL_PREFIX}{file_name}"


async def persist_upload(image_file: Optional[UploadFile]) -> Optional[str]:
    if image_file is None:
        return None
    image_bytes = await image_file.read()
    if not image_bytes:
        return None

    extension = _validate_image(image_file.content_type or "", image_bytes)
    RESCUE_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    file_name = f"{int(time.time())}_{uuid.uuid4().hex[:12]}{extension}"
    (RESCUE_IMAGE_DIR / file_name).write_bytes(image_bytes)
    return f"{RESCUE_IMAGE_URL_PREFIX}{file_name}"


def pack_message(
    text: Optional[str],
    rescue_type: Optional[str],
    province_city: Optional[str],
    source_link: Optional[str],
    image_url: Optional[str],
) -> Optional[str]:
    payload = {
        "text": (text or "").strip(),
        "rescue_type": (rescue_type or "").strip() or None,
        "province_city": (province_city or "").strip() or None,
        "source_link": (source_link or "").strip() or None,
        "image_url": (image_url or "").strip() or None,
        "image_data_url": None,
    }
    if not any(value for key, value in payload.items() if key != "text"):
        return payload["text"] or None
    return f"{RESCUE_META_PREFIX}{json.dumps(payload, ensure_ascii=False)}"


def unpack_message(raw_message: Optional[str]) -> dict:
    raw = raw_message or ""
    empty = {
        "text": raw,
        "rescue_type": None,
        "province_city": None,
        "source_link": None,
        "image_url": None,
        "image_data_url": None,
    }
    if not raw.startswith(RESCUE_META_PREFIX):
        return empty
    try:
        value = json.loads(raw[len(RESCUE_META_PREFIX):])
        return {
            "text": str(value.get("text") or ""),
            "rescue_type": str(value.get("rescue_type") or "") or None,
            "province_city": str(value.get("province_city") or "") or None,
            "source_link": str(value.get("source_link") or "") or None,
            "image_url": str(value.get("image_url") or "") or None,
            "image_data_url": str(value.get("image_data_url") or "") or None,
        }
    except (TypeError, ValueError, json.JSONDecodeError):
        return empty


def resolve_image_path(image_url: Optional[str]) -> Optional[Path]:
    url = (image_url or "").strip()
    prefix = next(
        (
            candidate
            for candidate in (
                RESCUE_IMAGE_URL_PREFIX,
                LEGACY_RESCUE_IMAGE_URL_PREFIX,
            )
            if url.startswith(candidate)
        ),
        None,
    )
    if prefix is None:
        return None
    file_name = url[len(prefix):].strip()
    if (
        not file_name
        or Path(file_name).name != file_name
        or SAFE_IMAGE_FILE_NAME.fullmatch(file_name) is None
    ):
        return None
    image_root = RESCUE_IMAGE_DIR.resolve()
    image_path = (image_root / file_name).resolve()
    if image_path.parent != image_root:
        return None
    return image_path


def protected_image_url(image_url: Optional[str]) -> Optional[str]:
    image_path = resolve_image_path(image_url)
    if image_path is None:
        return None
    return f"{RESCUE_IMAGE_URL_PREFIX}{image_path.name}"


def validated_image_media_type(image_path: Path) -> Optional[str]:
    mime_type = IMAGE_MIME_BY_EXTENSION.get(image_path.suffix.lower())
    if mime_type is None or not image_path.is_file():
        return None
    try:
        image_bytes = image_path.read_bytes()
        _validate_image(mime_type, image_bytes)
    except (HTTPException, OSError):
        return None
    return mime_type
