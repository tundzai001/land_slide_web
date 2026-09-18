"""Public rescue intake and administrative rescue workflow routes."""
import logging
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import UploadFile as StarletteUploadFile

from ... import auth
from ...database import get_data_db
from ...models import auth as model_auth
from ...models import data as model_data
from ...websocket import manager as ws_manager
from ..incidents.cases import append_event, ensure_incident_case, get_case_for_source, serialize_case
from ...shared.pagination import normalize_page, set_pagination_headers
from . import storage as rescue_storage

router = APIRouter()
logger = logging.getLogger(__name__)


class RescueRequestCreate(BaseModel):
    requester_name: Optional[str] = None
    phone: Optional[str] = None
    message: Optional[str] = None
    latitude: float
    longitude: float
    accuracy_m: Optional[float] = None
    rescue_type: Optional[str] = None
    province_city: Optional[str] = None
    source_link: Optional[str] = None
    image_data_url: Optional[str] = None


class RescueRequestUpdate(BaseModel):
    status: str
    admin_note: Optional[str] = None


def _require_admin(user: model_auth.User) -> None:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Not enough permissions")


@router.get("/api/admin/rescue-images/{file_name}")
async def get_rescue_image(
    file_name: str,
    current_user: model_auth.User = Depends(auth.get_current_user),
):
    _require_admin(current_user)
    image_path = rescue_storage.resolve_image_path(
        f"{rescue_storage.RESCUE_IMAGE_URL_PREFIX}{file_name}"
    )
    if image_path is None or image_path.name != file_name:
        raise HTTPException(status_code=404, detail="Rescue image not found")
    media_type = rescue_storage.validated_image_media_type(image_path)
    if media_type is None:
        raise HTTPException(status_code=404, detail="Rescue image not found")
    return FileResponse(
        image_path,
        media_type=media_type,
        headers={
            "Cache-Control": "private, no-store, max-age=0",
            "Content-Disposition": f'inline; filename="{file_name}"',
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/api/public/rescue-requests")
async def create_rescue_request(
    request: Request,
    db: AsyncSession = Depends(get_data_db),
):
    content_type = (request.headers.get("content-type") or "").lower()
    if "multipart/form-data" in content_type:
        form = await request.form()
        payload = RescueRequestCreate(
            requester_name=str(form.get("requester_name") or "").strip() or None,
            phone=str(form.get("phone") or "").strip() or None,
            message=str(form.get("message") or "").strip() or None,
            latitude=float(form.get("latitude") or 0),
            longitude=float(form.get("longitude") or 0),
            accuracy_m=(
                float(form.get("accuracy_m"))
                if form.get("accuracy_m") not in (None, "", "null")
                else None
            ),
            rescue_type=str(form.get("rescue_type") or "").strip() or None,
            province_city=str(form.get("province_city") or "").strip() or None,
            source_link=str(form.get("source_link") or "").strip() or None,
        )
        raw_file = form.get("image_file")
        image_url = await rescue_storage.persist_upload(
            raw_file if isinstance(raw_file, StarletteUploadFile) else None
        )
    else:
        payload = RescueRequestCreate(**(await request.json()))
        image_url = rescue_storage.persist_data_url(payload.image_data_url)

    if not -90.0 <= float(payload.latitude) <= 90.0:
        raise HTTPException(status_code=400, detail="Invalid latitude")
    if not -180.0 <= float(payload.longitude) <= 180.0:
        raise HTTPException(status_code=400, detail="Invalid longitude")

    now_ts = int(time.time())
    row = model_data.RescueRequest(
        created_at=now_ts,
        requester_name=(payload.requester_name or "").strip()[:120] or None,
        phone=(payload.phone or "").strip()[:32] or None,
        message=rescue_storage.pack_message(
            payload.message,
            payload.rescue_type,
            payload.province_city,
            payload.source_link,
            image_url,
        ),
        latitude=float(payload.latitude),
        longitude=float(payload.longitude),
        accuracy_m=float(payload.accuracy_m) if payload.accuracy_m is not None else None,
        status="pending",
    )
    db.add(row)
    await db.flush()
    incident_case, _created, incident_event = await ensure_incident_case(
        db,
        source_kind="RESCUE_REQUEST",
        source_id=int(row.id),
        title="Yêu cầu cứu hộ",
        summary="Yêu cầu cứu hộ mới cần được triage.",
        source_severity="UNKNOWN",
        signal_state="NOT_APPLICABLE",
        now=now_ts,
    )
    await db.commit()
    await db.refresh(row)
    if incident_event is not None:
        await db.refresh(incident_event)

    parsed = rescue_storage.unpack_message(row.message)
    try:
        await ws_manager.broadcast_operations(
            {
                "protocol": 2,
                "type": "incident_changed",
                "event_id": int(incident_event.id) if incident_event is not None else None,
                "sequence_from": incident_event.sequence if incident_event is not None else None,
                "sequence_to": incident_event.sequence if incident_event is not None else None,
                "incident_id": int(incident_case.id),
                "incident_revision": int(incident_case.revision),
                "workflow_version": int(incident_case.version),
                "action": "created" if _created else "updated",
                "project_id": incident_case.project_id,
                "station_id": incident_case.station_id,
                "summary": serialize_case(incident_case),
            }
        )
        await ws_manager.broadcast_admins(
            {
                "type": "rescue_request",
                "id": int(row.id),
                "created_at": row.created_at,
                "requester_name": row.requester_name,
                "phone": row.phone,
                "message": parsed["text"],
                "latitude": row.latitude,
                "longitude": row.longitude,
                "accuracy_m": row.accuracy_m,
                "status": row.status,
                "rescue_type": parsed["rescue_type"],
                "province_city": parsed["province_city"],
                "source_link": parsed["source_link"],
                "image_url": rescue_storage.protected_image_url(parsed["image_url"]),
            }
        )
    except Exception as exc:
        logger.warning("WS rescue_request broadcast failed: %s", exc)
    return {"status": "ok", "id": int(row.id), "created_at": row.created_at}


@router.get("/api/admin/rescue-requests")
async def get_rescue_requests(
    response: Response,
    status_filter: Optional[str] = None,
    status: Optional[str] = None,
    q: Optional[str] = None,
    offset: int = 0,
    limit: int = 100,
    sort: str = "-created_at",
    db: AsyncSession = Depends(get_data_db),
    current_user: model_auth.User = Depends(auth.get_current_user),
):
    _require_admin(current_user)
    query = select(model_data.RescueRequest)
    normalized = (status or status_filter or "").strip().lower()
    if normalized in ("pending", "resolved", "rejected"):
        query = query.where(model_data.RescueRequest.status == normalized)
    normalized_q = (q or "").strip()
    if normalized_q:
        pattern = f"%{normalized_q}%"
        query = query.where(or_(
            model_data.RescueRequest.requester_name.ilike(pattern),
            model_data.RescueRequest.phone.ilike(pattern),
            model_data.RescueRequest.message.ilike(pattern),
        ))
    page_offset, page_limit = normalize_page(offset, limit)
    sort_fields = {
        "created_at": model_data.RescueRequest.created_at,
        "status": model_data.RescueRequest.status,
        "requester_name": model_data.RescueRequest.requester_name,
    }
    field_name = sort.lstrip("-")
    if field_name not in sort_fields:
        raise HTTPException(status_code=422, detail="Unsupported sort field")
    order_column = sort_fields[field_name]
    query = query.order_by(order_column.desc() if sort.startswith("-") else order_column.asc())
    count_query = select(func.count()).select_from(query.order_by(None).subquery())
    total = int((await db.execute(count_query)).scalar() or 0)
    query = query.offset(page_offset).limit(page_limit)
    set_pagination_headers(response, total=total, offset=page_offset, limit=page_limit)
    rows = (await db.execute(query)).scalars().all()
    result = []
    for row in rows:
        parsed = rescue_storage.unpack_message(row.message)
        result.append(
            {
                "id": int(row.id),
                "created_at": int(row.created_at),
                "requester_name": row.requester_name,
                "phone": row.phone,
                "message": parsed["text"],
                "latitude": row.latitude,
                "longitude": row.longitude,
                "accuracy_m": row.accuracy_m,
                "status": row.status,
                "admin_note": row.admin_note,
                "handled_by": row.handled_by,
                "handled_at": row.handled_at,
                "rescue_type": parsed["rescue_type"],
                "province_city": parsed["province_city"],
                "source_link": parsed["source_link"],
                "image_url": rescue_storage.protected_image_url(parsed["image_url"]),
            }
        )
    return result


@router.patch("/api/admin/rescue-requests/{request_id}")
async def update_rescue_request(
    request_id: int,
    payload: RescueRequestUpdate,
    db: AsyncSession = Depends(get_data_db),
    current_user: model_auth.User = Depends(auth.get_current_user),
):
    _require_admin(current_user)
    new_status = (payload.status or "").strip().lower()
    if new_status not in ("pending", "resolved", "rejected"):
        raise HTTPException(status_code=400, detail="Invalid status")
    row = (
        await db.execute(
            select(model_data.RescueRequest).where(model_data.RescueRequest.id == request_id)
        )
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Rescue request not found")

    row.status = new_status
    row.admin_note = (payload.admin_note or "").strip()[:500] or None
    if new_status in ("resolved", "rejected"):
        row.handled_by = current_user.username
        row.handled_at = int(time.time())
    else:
        row.handled_by = None
        row.handled_at = None
    incident_case = await get_case_for_source(db, "RESCUE_REQUEST", int(row.id), for_update=True)
    incident_event = None
    if incident_case is not None:
        target_status = {
            "pending": "in_progress" if incident_case.status in {"resolved", "dismissed"} else incident_case.status,
            "resolved": "resolved",
            "rejected": "dismissed",
        }[new_status]
        status_changed = incident_case.status != target_status
        reopened = incident_case.status in {"resolved", "dismissed"} and target_status == "in_progress"
        incident_case.status = target_status
        incident_case.resolved_at = int(time.time()) if target_status == "resolved" else None
        if status_changed:
            incident_case.version += 1
            incident_event = await append_event(
                db,
                incident_case,
                "status_changed",
                actor_kind="user",
                actor_user_id=int(current_user.id),
                actor_username=current_user.username,
                note=payload.admin_note or ("legacy_reopen" if reopened else None),
                payload={"status": target_status, "legacy_reopen": reopened},
            )
    await db.commit()
    if incident_event is not None:
        await db.refresh(incident_event)
        await ws_manager.broadcast_operations({
            "protocol": 2,
            "type": "incident_changed",
            "event_id": int(incident_event.id),
            "sequence_from": int(incident_event.sequence),
            "sequence_to": int(incident_event.sequence),
            "incident_id": int(incident_case.id),
            "incident_revision": int(incident_case.revision),
            "workflow_version": int(incident_case.version),
            "action": "updated",
            "project_id": incident_case.project_id,
            "station_id": incident_case.station_id,
            "summary": serialize_case(incident_case),
        })
    return {"status": "ok", "id": int(row.id), "new_status": row.status}


@router.delete("/api/admin/rescue-requests/{request_id}")
async def delete_rescue_request(
    request_id: int,
    db: AsyncSession = Depends(get_data_db),
    current_user: model_auth.User = Depends(auth.get_current_user),
):
    _require_admin(current_user)
    row = (
        await db.execute(
            select(model_data.RescueRequest).where(model_data.RescueRequest.id == request_id)
        )
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Rescue request not found")
    if row.status == "pending":
        raise HTTPException(
            status_code=400,
            detail="Cannot delete pending request. Resolve or reject first",
        )

    target_image_url = rescue_storage.unpack_message(row.message).get("image_url")
    can_delete_image = False
    if target_image_url:
        other_rows = (
            await db.execute(
                select(model_data.RescueRequest).where(model_data.RescueRequest.id != request_id)
            )
        ).scalars().all()
        can_delete_image = not any(
            (rescue_storage.unpack_message(other.message).get("image_url") or "").strip()
            == str(target_image_url).strip()
            for other in other_rows
        )

    cleanup_job = None
    if can_delete_image and target_image_url:
        now_ts = int(time.time())
        upload_id = str(uuid.uuid5(uuid.NAMESPACE_URL, str(target_image_url)))
        existing_job = (
            await db.execute(
                select(model_data.FileCleanupJob).where(
                    model_data.FileCleanupJob.upload_id == upload_id,
                    model_data.FileCleanupJob.job_generation == 0,
                )
            )
        ).scalar_one_or_none()
        if existing_job is None:
            db.add(model_data.FileCleanupJob(
                upload_id=upload_id,
                image_storage_key=str(target_image_url)[:255],
                job_generation=0,
                status="PENDING",
                attempts=0,
                run_after=now_ts,
                created_at=now_ts,
                updated_at=now_ts,
            ))

    await db.delete(row)
    await db.commit()
    return {"status": "ok", "deleted_id": int(request_id)}
