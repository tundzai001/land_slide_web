"""Encoding and image-storage helpers for rescue requests."""
import base64
import binascii
import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, UploadFile

RESCUE_META_PREFIX = "__RESCUE_META_V1__"
RESCUE_IMAGE_DIR = Path(__file__).resolve().parents[2] / "static" / "uploads" / "rescue"
RESCUE_IMAGE_URL_PREFIX = "/static/uploads/rescue/"
MAX_RESCUE_IMAGE_BYTES = 400 * 1024
IMAGE_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


def _validate_image(mime_type: str, image_bytes: bytes) -> str:
    extension = IMAGE_EXTENSIONS.get((mime_type or "").lower())
    if not extension:
        raise HTTPException(status_code=400, detail="Unsupported image type")
    if len(image_bytes) > MAX_RESCUE_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail="Image too large")
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
    if not url.startswith(RESCUE_IMAGE_URL_PREFIX):
        return None
    file_name = url[len(RESCUE_IMAGE_URL_PREFIX):].strip()
    if not file_name or Path(file_name).name != file_name:
        return None
    return RESCUE_IMAGE_DIR / file_name
