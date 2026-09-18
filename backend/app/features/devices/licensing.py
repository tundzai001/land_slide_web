"""Device licensing and provisioning routes."""

from __future__ import annotations

import json
import math
import time
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ... import auth
from ...database import get_config_db
from ...models import auth as model_auth
from ...models import config as model_config

router = APIRouter(prefix="/api/admin", tags=["Admin Console"])

def get_license_code_from_string(string_number: str) -> str:
    """Tạo mã license từ một chuỗi số, thuật toán xáo trộn."""
    try:
        length = len(string_number)
        if length == 0:
            return ""
        arr = [0] * (length + 1)
        narr = [0.0] * (length + 1)
        number = float(string_number)
        r_string = ""
        n = length
        number *= n
        arr[0] = int(number * math.pow(10.0, -float(n)))
        for i in range(1, length):
            number = number - float(arr[i - 1]) / math.pow(10.0, -float(n))
            n -= 1
            arr[i] = int(number * math.pow(10, -float(n)))
        arr[length] = (arr[length - 2] + arr[length - 1]) / 2 + 1
        narr[0] = float(arr[0])
        for i in range(1, length + 1):
            narr[i] = (narr[i - 1] + float(arr[i])) / 2.0
        for i in range(length):
            A = narr[i + 1] * math.exp(-0.2)
            # guard against math domain error
            B = 0
            try:
                if arr[length] > 0 and arr[i + 1] > 0:
                    B = (math.log(arr[length], 10)) * math.pow(arr[i + 1], 0.2)
            except Exception:
                B = 0
            r_string += str(int(round(A + B)))
        return r_string
    except (ValueError, IndexError, TypeError, ZeroDivisionError):
        return ""


class ProvisionDeviceRequest(BaseModel):
    device_code: str
    station_id: int
    license: Optional[str] = None
    mqtt_topic: Optional[str] = None


@router.get("/devices/pending")
async def get_pending_devices(
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    """Return devices that are not yet assigned to a station (waiting for provisioning).
    Devices created by field units during registration are created with station_id=0.
    """
    try:
        res = await db.execute(
            select(model_config.Device).where(model_config.Device.station_id == 0)
        )
        devices = res.scalars().all()

        # Simplify output for frontend
        out = []
        for d in devices:
            out.append({
                "id": d.id,
                "device_code": d.device_code,
                "name": d.name,
                "device_type": d.device_type,
                "mqtt_topic": d.mqtt_topic,
                "created_at": d.created_at,
                "config": d.config or {}
            })

        return out
    except Exception as e:
        logger.error(f"Error fetching pending devices: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/devices/generate-license")
async def generate_license_for_device(
    payload: Dict[str, Any],
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    """Generate a license for a device and push it to the field unit via MQTT (if possible).
    Payload: {"device_code": "HW123", "customer_id": "OptionalCustomer"}
    """
    device_code = payload.get('device_code')
    customer_id = payload.get('customer_id', '')
    if not device_code:
        raise HTTPException(status_code=400, detail="device_code required")

    try:
        res = await db.execute(select(model_config.Device).where(model_config.Device.device_code == device_code))
        device = res.scalar_one_or_none()
        if not device:
            raise HTTPException(status_code=404, detail="Device not found")

        # Use device_code (serial) as base for generation
        pi_base = generate_pi_license_base(device.device_code)
        customer_base = generate_customer_license_base(customer_id or device.name or "CUSTOMER")

        # Combine bases then produce license string
        combined = pi_base + customer_base
        license_code = get_license_code_from_string(combined)

        # Persist license into device.config
        cfg = device.config or {}
        cfg['license'] = license_code
        cfg['license_generated_by'] = current_user.username
        cfg['license_generated_at'] = int(time.time())
        device.config = cfg
        db.add(device)
        await db.commit()
        await db.refresh(device)

        # Attempt to push license to device via MQTT command
        pushed = False
        try:
            # late import to avoid circular
            from ...runtime import mqtt_service
            # Pi subscribes to landslide/{station_id}/command
            cmd_topic = f"landslide/{device.station_id}/command"
            payload_msg = json.dumps({
                "cmd": "install_license",
                "license": license_code,
                "device_code": device.device_code,
                "customer_base": customer_base
            })
            mqtt_service.client.publish(cmd_topic, payload_msg)
            pushed = True
            logger.info(f"📡 License pushed to {cmd_topic}")
        except Exception as e:
            logger.warning(f"Could not push license via MQTT: {e}")

        return {"status": "ok", "license": license_code, "pushed": pushed}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating license: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/devices/provision")
async def provision_device(
    payload: ProvisionDeviceRequest,
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    """Admin action to assign a waiting device to a station and mark it provisioned.
    This updates the device.station_id, mqtt_topic and writes provision metadata to device.config.
    """
    try:
        res = await db.execute(select(model_config.Device).where(model_config.Device.device_code == payload.device_code))
        device = res.scalar_one_or_none()
        if not device:
            raise HTTPException(status_code=404, detail="Device not found")

        # Update station assignment and mqtt topic
        device.station_id = payload.station_id
        if payload.mqtt_topic:
            device.mqtt_topic = payload.mqtt_topic

        # Update config metadata
        cfg = device.config or {}
        cfg['provisioned'] = True
        if payload.license:
            cfg['license'] = payload.license
        cfg['provisioned_by'] = current_user.username
        cfg['provisioned_at'] = int(time.time())
        device.config = cfg

        await db.commit()
        await db.refresh(device)

        return {"status": "ok", "device_code": device.device_code, "station_id": device.station_id}
    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error provisioning device: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def generate_customer_license_base(identifier: str) -> str:
    """Tạo chuỗi số cơ sở từ định danh của khách hàng."""
    processed_id = ''.join(filter(str.isalnum, identifier.upper()))
    if len(processed_id) > 12:
        return processed_id[:12]
    return processed_id.ljust(12, '0')


def generate_pi_license_base(serial_number: str) -> str:
    """Tạo chuỗi số cơ sở từ Serial Number của Pi."""
    base_code_str = ""
    temp_str = ""
    # Chỉ lấy 10 ký tự cuối của serial để tạo mã ngắn gọn và nhất quán
    s_number_part = serial_number[-10:]

    for c in s_number_part:
        temp_str += c.upper() if 'a' <= c.lower() <= 'z' else c

    for char in temp_str:
        base_code_str += str(ord(char))

    # Đảm bảo chuỗi số luôn có độ dài 12
    if len(base_code_str) > 12:
        return base_code_str[:12]
    else:
        return base_code_str.ljust(12, '0')
