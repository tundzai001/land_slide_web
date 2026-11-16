"""Field Pi-device HTTP endpoints."""

from __future__ import annotations

import logging
import time
import math
import json
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Response, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import or_, select
from ... import config as app_config
from ...database import get_config_db
from ... import auth
from ...models import config as model_config
from ...models.pi_device import PiDevice
from ...shared.pagination import normalize_page, set_pagination_headers

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/field", tags=["Field Unit API"])

def _get_license_code_from_string(string_number: str) -> str:
    try:
        length = len(string_number)
        if length == 0:
            return ""
        arr = [0] * (length + 1)
        narr = [0.0] * (length + 1)
        number = float(string_number)
        n = length
        number *= n
        arr[0] = int(number * (10.0 ** -float(n)))
        for i in range(1, length):
            number = number - float(arr[i - 1]) / (10.0 ** -float(n))
            n -= 1
            arr[i] = int(number * (10 ** -float(n)))
        arr[length] = (arr[length - 2] + arr[length - 1]) / 2 + 1
        narr[0] = float(arr[0])
        for i in range(1, length + 1):
            narr[i] = (narr[i - 1] + float(arr[i])) / 2.0
        r_string = ""
        for i in range(length):
            A = narr[i + 1] * math.exp(-0.2)
            B = 0
            try:
                if arr[length] > 0 and arr[i + 1] > 0:
                    B = (math.log(arr[length], 10)) * math.pow(arr[i + 1], 0.2)
            except Exception:
                B = 0
            r_string += str(int(round(A + B)))
        return r_string
    except Exception:
        return ""


def _generate_pi_license_base(serial: str) -> str:
    s_number_part = serial[-10:]
    temp_str = ""
    for c in s_number_part:
        temp_str += c.upper() if 'a' <= c.lower() <= 'z' else c
    base_code_str = ""
    for char in temp_str:
        base_code_str += str(ord(char))
    if len(base_code_str) > 12:
        return base_code_str[:12]
    return base_code_str.ljust(12, '0')


def _generate_customer_license_base(identifier: str = "CUSTOMER") -> str:
    """Convert identifier to all-numeric base using ord() - must match Pi-side logic exactly."""
    base_code_str = ""
    for char in identifier.upper():
        base_code_str += str(ord(char))
    if len(base_code_str) > 12:
        return base_code_str[:12]
    return base_code_str.ljust(12, '0')


def generate_activation_key(serial: str) -> str:
    """Generate activation key from Pi serial number (same algorithm as Pi-side)."""
    pi_base   = _generate_pi_license_base(serial)
    cust_base = _generate_customer_license_base("CUSTOMER")
    return _get_license_code_from_string(pi_base + cust_base)


def _publish_mqtt(topic: str, payload: dict):
    """Publish a JSON message to MQTT broker (fire and forget)."""
    try:
        import paho.mqtt.client as mqtt
        cfg = app_config.settings
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, client_id="backend-field-pub")
        client.username_pw_set(cfg.MQTT_USER, cfg.MQTT_PASSWORD)
        client.connect(cfg.MQTT_BROKER, cfg.MQTT_PORT, keepalive=10)
        client.publish(topic, json.dumps(payload), qos=1)
        client.disconnect()
        logger.info(f"📡 MQTT published to {topic}: {payload}")
    except Exception as e:
        logger.warning(f"⚠️ MQTT publish failed (non-critical): {e}")


class PiRegisterRequest(BaseModel):
    serial: str          # Unique identifier (CPU serial or generated)
    name:   str
    device_type: str = "pi"


class PiRegisterResponse(BaseModel):
    device_id: int
    status:    str
    station_id: Optional[int] = None


class PiConfirmRequest(BaseModel):
    activated: bool
    serial:    str


class PiAssignRequest(BaseModel):
    station_id: int


class PiAssignToCenterRequest(BaseModel):
    pi_center_id: int


@router.post("/register", response_model=PiRegisterResponse, responses={500: {"description": "Internal Server Error"}})
async def register_pi_device(
    payload: PiRegisterRequest,
    db: AsyncSession = Depends(get_config_db)
):
    """
    Pi calls this on first boot to register itself.
    Creates a PiDevice record with status='pending' if not already registered.
    """
    try:
        res = await db.execute(
            select(PiDevice).where(PiDevice.serial == payload.serial)
        )
        pi = res.scalar_one_or_none()
        current_time = int(time.time())

        if pi:
            # Update last_seen and return existing record
            pi.last_seen = current_time
            pi.device_type = payload.device_type

            # Auto-confirm: if status is stuck at 'activating' and license matches, promote to 'activated'
            clean_serial = payload.serial.replace("\r", "").replace("\n", "")
            if pi.status == "activating" and pi.license_key:
                expected_key = generate_activation_key(pi.serial)
                if pi.license_key == expected_key:
                    pi.status = "activated"
                    logger.info("✅ Auto-confirmed Pi '%s' (license matched on reconnect)", clean_serial)

            await db.commit()
            logger.info("🔄 Pi reconnect: %s (status=%s)", clean_serial, pi.status)
            return {
                "device_id": pi.id,
                "status":    pi.status,
                "station_id": pi.station_id
            }
        else:
            # New Pi device
            clean_serial = payload.serial.replace("\r", "").replace("\n", "")
            clean_type = payload.device_type.replace("\r", "").replace("\n", "")
            logger.info("✨ New Pi registration: %s (%s)", clean_serial, clean_type)
            new_pi = PiDevice(
                serial        = payload.serial,
                name          = payload.name,
                device_type   = payload.device_type,
                status        = "pending",
                station_id    = None,
                license_key   = None,
                last_seen     = current_time,
                registered_at = current_time,
                extra_config  = {}
            )
            db.add(new_pi)
            await db.commit()
            await db.refresh(new_pi)
            return {
                "device_id": new_pi.id,
                "status":    "pending",
                "station_id": None
            }

    except Exception as e:
        logger.exception(f"Error registering Pi device: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/heartbeat", responses={500: {"description": "Internal Server Error"}})
async def heartbeat_pi_device(
    payload: PiRegisterRequest,
    db: AsyncSession = Depends(get_config_db)
):
    """
    Lightweight keep-alive used by Pi devices in their background loop.
    Avoids spamming the main register logs and bypasses heavy DB creations.
    """
    try:
        res = await db.execute(
            select(PiDevice).where(PiDevice.serial == payload.serial)
        )
        pi = res.scalar_one_or_none()
        current_time = int(time.time())

        if pi:
            pi.last_seen = current_time
            await db.commit()
            return {"status": "ok", "message": "Heartbeat accepted"}
        else:
            # If deleted or not found, tell it to register again
            return {"status": "error", "message": "Not registered"}

    except Exception:
        # Ignore errors for heartbeats to prevent log spam
        raise HTTPException(status_code=500, detail="Heartbeat failed")


@router.get("/pi-devices", responses={422: {"description": "Unprocessable Entity"}, 500: {"description": "Internal Server Error"}})
async def list_pi_devices(
    response: Response,
    q: Optional[str] = None,
    status_filter: Optional[str] = None,
    device_status: Optional[str] = Query(None, alias="status"),
    station_id: Optional[int] = None,
    offset: Optional[int] = None,
    limit: Optional[int] = None,
    sort: str = "-registered_at",
    db: AsyncSession = Depends(get_config_db),
    _user=Depends(auth.require_permission(auth.Permission.VIEW_FIELD_DEVICES))
):
    """List all registered Pi devices (admin only)."""
    try:
        query = select(PiDevice)
        if q and q.strip():
            pattern = f"%{q.strip()}%"
            query = query.where(or_(PiDevice.name.ilike(pattern), PiDevice.serial.ilike(pattern)))
        normalized_status = (device_status or status_filter or "").strip().lower()
        if normalized_status:
            query = query.where(PiDevice.status == normalized_status)
        if station_id is not None:
            query = query.where(PiDevice.station_id == station_id)
        sort_fields = {"registered_at": PiDevice.registered_at, "last_seen": PiDevice.last_seen, "name": PiDevice.name, "status": PiDevice.status}
        field_name = sort.lstrip("-")
        if field_name not in sort_fields:
            raise HTTPException(status_code=422, detail="Unsupported sort field")
        order_column = sort_fields[field_name]
        query = query.order_by(order_column.desc() if sort.startswith("-") else order_column.asc())
        page_offset, page_limit = normalize_page(offset, limit)
        all_devices = list((await db.execute(query)).scalars().all())
        set_pagination_headers(response, total=len(all_devices), offset=page_offset, limit=page_limit)
        devices = all_devices[page_offset:] if page_limit is None else all_devices[page_offset:page_offset + page_limit]

        # Fetch station + project info for assigned devices
        station_info = {}  # station_id -> {name, project_name}
        station_ids = [d.station_id for d in devices if d.station_id]
        if station_ids:
            s_res = await db.execute(
                select(model_config.Station).where(model_config.Station.id.in_(station_ids))
            )
            stations = s_res.scalars().all()
            # Fetch project names
            project_ids = list(set(s.project_id for s in stations if s.project_id))
            project_names = {}
            if project_ids:
                p_res = await db.execute(
                    select(model_config.Project).where(model_config.Project.id.in_(project_ids))
                )
                for p in p_res.scalars().all():
                    project_names[p.id] = p.name
            for s in stations:
                station_info[s.id] = {
                    "name": s.name,
                    "project_id": s.project_id,
                    "project_name": project_names.get(s.project_id, ""),
                }

        # Fetch Pi Center info for Pi Points
        center_info = {} # center_id -> {name, serial}
        center_ids = [getattr(d, "pi_center_id", None) for d in devices if getattr(d, "pi_center_id", None)]
        if center_ids:
            c_res = await db.execute(
                select(PiDevice).where(PiDevice.id.in_(center_ids))
            )
            for c in c_res.scalars().all():
                center_info[c.id] = {"name": c.name, "serial": c.serial}

        return [
            {
                "id":            d.id,
                "serial":        d.serial,
                "name":          d.name,
                "device_type":   getattr(d, "device_type", "pi"),
                "status":        d.status,
                "is_locked":     getattr(d, 'is_locked', False),
                "station_id":    d.station_id,
                "station_name":  station_info.get(d.station_id, {}).get("name"),
                "project_id":    station_info.get(d.station_id, {}).get("project_id"),
                "project_name":  station_info.get(d.station_id, {}).get("project_name"),
                "pi_center_id":  getattr(d, "pi_center_id", None),
                "pi_center_name": center_info.get(getattr(d, "pi_center_id", None), {}).get("name"),
                "pi_center_serial": center_info.get(getattr(d, "pi_center_id", None), {}).get("serial"),
                "last_seen":     d.last_seen,
                "registered_at": d.registered_at,
            }
            for d in devices
        ]
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error listing Pi devices: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/pi-devices/available", responses={500: {"description": "Internal Server Error"}})
async def list_available_pi_devices(
    db: AsyncSession = Depends(get_config_db),
    _user=Depends(auth.require_permission(auth.Permission.VIEW_FIELD_DEVICES))
):
    """Return Pi devices that are activated but NOT yet assigned to any station."""
    try:
        res = await db.execute(
            select(PiDevice).where(PiDevice.status == "activated")
        )
        devices = res.scalars().all()
        return [
            {"id": d.id, "serial": d.serial, "name": d.name, "last_seen": d.last_seen}
            for d in devices
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/pi-devices/{pi_id}/activate", responses={400: {"description": "Bad Request"}, 404: {"description": "Not Found"}, 500: {"description": "Internal Server Error"}})
async def activate_pi_device(
    pi_id: int,
    db: AsyncSession = Depends(get_config_db),
    _user=Depends(auth.require_permission(auth.Permission.MANAGE_FIELD_DEVICES))
):
    """
    Admin activates a Pi:
    1. Generate license key from serial
    2. Mark status = 'activating'
    3. Send key to Pi via MQTT on topic landslide/pi/{serial}/command
    """
    try:
        res = await db.execute(select(PiDevice).where(PiDevice.id == pi_id))
        pi = res.scalar_one_or_none()
        if not pi:
            raise HTTPException(status_code=404, detail="Pi device not found")
        if pi.status not in ("pending", "activating"):
            raise HTTPException(status_code=400, detail=f"Pi is already '{pi.status}'")

        # Generate license key
        key = generate_activation_key(pi.serial)
        pi.license_key = key
        pi.status      = "activating"
        await db.commit()

        # Send via MQTT (fire and forget)
        topic = f"landslide/pi/{pi.serial}/command"
        _publish_mqtt(topic, {
            "cmd":         "install_license",
            "device_id":   pi.id,
            "device_code": pi.serial,
            "license":     key,
            "customer_base": _generate_customer_license_base("CUSTOMER")
        })

        logger.info(f"🔑 Activation sent to Pi '{pi.serial}' (key={key})")
        return {"status": "activating", "message": "License key sent to Pi via MQTT"}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error activating Pi: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/pi-devices/{pi_id}/confirm", responses={404: {"description": "Not Found"}, 500: {"description": "Internal Server Error"}})
async def confirm_pi_activation(
    pi_id: int,
    payload: PiConfirmRequest,
    db: AsyncSession = Depends(get_config_db)
):
    """
    Pi calls this after verifying its license key locally.
    Updates status to 'activated' or back to 'pending' on failure.
    """
    try:
        res = await db.execute(select(PiDevice).where(PiDevice.id == pi_id))
        pi = res.scalar_one_or_none()
        if not pi:
            raise HTTPException(status_code=404, detail="Pi device not found")

        pi.last_seen = int(time.time())

        if payload.activated:
            pi.status = "activated"
            logger.info(f"✅ Pi '{pi.serial}' activation confirmed")
        else:
            pi.status = "pending"
            pi.license_key = None
            logger.warning(f"❌ Pi '{pi.serial}' activation failed (key mismatch)")

        await db.commit()
        return {"status": pi.status}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/pi-devices/{pi_id}/assign", responses={400: {"description": "Bad Request"}, 404: {"description": "Not Found"}, 500: {"description": "Internal Server Error"}})
async def assign_pi_to_station(
    pi_id: int,
    payload: PiAssignRequest,
    db: AsyncSession = Depends(get_config_db),
    _user=Depends(auth.require_permission(auth.Permission.ASSIGN_FIELD_DEVICES))
):
    """
    Admin assigns an activated Pi to a station.
    Sends MQTT command so Pi updates its local config.
    """
    try:
        res = await db.execute(select(PiDevice).where(PiDevice.id == pi_id))
        pi = res.scalar_one_or_none()
        if not pi:
            raise HTTPException(status_code=404, detail="Pi device not found")
        if getattr(pi, 'device_type', '') == 'pi_point':
            raise HTTPException(status_code=400, detail="Pi Point phải được gán qua Pi Center, không gán trực tiếp vào trạm")
        if pi.status not in ("activated", "assigned"):
            raise HTTPException(status_code=400, detail=f"Pi must be 'activated' first (current: {pi.status})")

        # Verify station exists
        s_res = await db.execute(
            select(model_config.Station).where(model_config.Station.id == payload.station_id)
        )
        station = s_res.scalar_one_or_none()
        if not station:
            raise HTTPException(status_code=404, detail="Station not found")

        pi.station_id = payload.station_id
        pi.status     = "assigned"
        await db.commit()

        # Notify Pi via MQTT
        topic = f"landslide/pi/{pi.serial}/command"
        _publish_mqtt(topic, {
            "cmd":        "set_station",
            "station_id": payload.station_id,
        })

        logger.info(f"📍 Pi '{pi.serial}' assigned to station {payload.station_id} ({station.name})")
        return {"status": "assigned", "station_id": payload.station_id, "station_name": station.name}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error assigning Pi: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/pi-devices/{pi_id}/unassign", responses={404: {"description": "Not Found"}, 500: {"description": "Internal Server Error"}})
async def unassign_pi(
    pi_id: int,
    db: AsyncSession = Depends(get_config_db),
    _user=Depends(auth.require_permission(auth.Permission.ASSIGN_FIELD_DEVICES))
):
    """Remove Pi from its station (set back to 'activated')."""
    try:
        res = await db.execute(select(PiDevice).where(PiDevice.id == pi_id))
        pi = res.scalar_one_or_none()
        if not pi:
            raise HTTPException(status_code=404, detail="Pi device not found")

        old_station = pi.station_id
        pi.station_id = None
        pi.pi_center_id = None
        pi.status     = "activated"
        await db.commit()

        logger.info(f"🔓 Pi '{pi.serial}' unassigned from station {old_station} and center")
        
        # Notify local Pi to clear its station_id
        topic = f"landslide/pi/{pi.serial}/command"
        _publish_mqtt(topic, {"cmd": "set_station", "station_id": None})

        return {"status": "activated"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/pi-devices/{pi_id}/lock", responses={404: {"description": "Not Found"}, 500: {"description": "Internal Server Error"}})
async def toggle_lock_pi_device(
    pi_id: int,
    db: AsyncSession = Depends(get_config_db),
    _user=Depends(auth.require_permission(auth.Permission.MANAGE_FIELD_DEVICES))
):
    """Toggle lock/unlock a Pi device."""
    try:
        res = await db.execute(select(PiDevice).where(PiDevice.id == pi_id))
        pi = res.scalar_one_or_none()
        if not pi:
            raise HTTPException(status_code=404, detail="Pi device not found")

        pi.is_locked = not getattr(pi, 'is_locked', False)
        await db.commit()

        state = "locked" if pi.is_locked else "unlocked"
        logger.info(f"🔒 Pi '{pi.serial}' {state}")

        # Notify Pi via MQTT
        topic = f"landslide/pi/{pi.serial}/command"
        _publish_mqtt(topic, {"cmd": "lock" if pi.is_locked else "unlock"})

        return {"status": state, "is_locked": pi.is_locked}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/pi-devices/{pi_id}", responses={404: {"description": "Not Found"}, 500: {"description": "Internal Server Error"}})
async def delete_pi_device(
    pi_id: int,
    db: AsyncSession = Depends(get_config_db),
    _user=Depends(auth.require_permission(auth.Permission.MANAGE_FIELD_DEVICES))
):
    """Delete a Pi device record."""
    try:
        res = await db.execute(select(PiDevice).where(PiDevice.id == pi_id))
        pi = res.scalar_one_or_none()
        if not pi:
            raise HTTPException(status_code=404, detail="Pi device not found")

        await db.delete(pi)
        await db.commit()
        logger.info(f"🗑️ Pi device deleted: {pi.serial}")
        return {"status": "deleted"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/pi-devices/{pi_id}/reset", responses={404: {"description": "Not Found"}, 500: {"description": "Internal Server Error"}})
async def reset_pi_device(
    pi_id: int,
    db: AsyncSession = Depends(get_config_db),
    _user=Depends(auth.require_permission(auth.Permission.MANAGE_FIELD_DEVICES))
):
    """Factory-reset a Pi device: clear license, station, set status back to pending."""
    try:
        res = await db.execute(select(PiDevice).where(PiDevice.id == pi_id))
        pi = res.scalar_one_or_none()
        if not pi:
            raise HTTPException(status_code=404, detail="Pi device not found")

        old_serial = pi.serial
        pi.status      = "pending"
        pi.station_id  = None
        pi.license_key = None
        pi.extra_config = {}
        await db.commit()

        logger.info(f"🔄 Pi device reset: {old_serial}")

        # Send MQTT reset command so the Pi clears its local config too
        try:
            mqtt_client = app_config.settings.get("mqtt_client")
            if mqtt_client:
                import json as _json
                topic = f"landslide/pi/{old_serial}/command"
                payload = _json.dumps({"cmd": "reset"})
                mqtt_client.publish(topic, payload)
                logger.info(f"📡 Reset command sent via MQTT to {topic}")
        except Exception as mqtt_err:
            logger.warning(f"MQTT reset publish failed: {mqtt_err}")

        return {"status": "pending", "serial": old_serial}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/pi-devices/{pi_id}/assign-to-center", responses={400: {"description": "Bad Request"}, 404: {"description": "Not Found"}, 500: {"description": "Internal Server Error"}})
async def assign_pi_to_center(
    pi_id: int,
    payload: PiAssignToCenterRequest,
    db: AsyncSession = Depends(get_config_db),
    _user=Depends(auth.require_permission(auth.Permission.MANAGE_FIELD_DEVICES))
):
    """Assign a pi_point device to a pi_center device."""
    try:
        # 1. Tìm Pi Hiện Trường
        res = await db.execute(select(PiDevice).where(PiDevice.id == pi_id))
        pi_point = res.scalar_one_or_none()
        if not pi_point:
            raise HTTPException(status_code=404, detail="Pi Point device not found")
        
        if pi_point.status != "activated":
            raise HTTPException(status_code=400, detail="Pi Point must be activated before assigning")
            
        # 2. Tìm Pi Trung Tâm
        res_center = await db.execute(select(PiDevice).where(PiDevice.id == payload.pi_center_id))
        pi_center = res_center.scalar_one_or_none()
        if not pi_center:
            raise HTTPException(status_code=404, detail="Pi Center device not found")
            
        if pi_center.pi_center_id is not None:
             raise HTTPException(status_code=400, detail="Target device is also a pi_point. Must link to a pi_center.")
             
        if pi_center.status != "assigned" or not pi_center.station_id:
            raise HTTPException(status_code=400, detail="Pi Center must be assigned to a station first")

        # 3. Gắn Pi Point vào Pi Center
        pi_point.pi_center_id = pi_center.id
        pi_point.station_id = pi_center.station_id
        pi_point.status = "assigned"

        await db.commit()
        
        logger.info(f"✅ Assigned Pi Point {pi_point.serial} to Pi Center {pi_center.serial} (Station {pi_center.station_id})")

        # 4. Gửi MQTT báo cho Pi Point biết nó đã thuộc trạm nào
        try:
            import json
            import paho.mqtt.publish as publish
            
            # Use pi command topic to configure the field unit
            pi_topic = f"landslide/pi/{pi_point.serial}/command"
            payload_data = json.dumps({
                "cmd": "set_station",
                "station_id": pi_center.station_id
            })
            
            # Optional: Lấy config MQTT
            from app.config import settings
            auth_info = None
            if settings.MQTT_USER and settings.MQTT_PASSWORD:
                auth_info = {'username': settings.MQTT_USER, 'password': settings.MQTT_PASSWORD}
                
            logger.info(f"📡 Sending set_station command to {pi_topic}")
            publish.single(
                topic=pi_topic,
                payload=payload_data,
                hostname=settings.MQTT_BROKER,
                port=settings.MQTT_PORT,
                auth=auth_info,
                qos=1
            )
        except Exception as e:
            logger.exception(f"Failed to send MQTT set_station for pi point: {e}")

        return {"status": "assigned", "station_id": pi_center.station_id, "pi_center_id": pi_center.id}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error assigning pi to center: {e}")
        raise HTTPException(status_code=500, detail=str(e))
