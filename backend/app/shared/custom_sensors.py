"""Reusable custom sensor definitions in the existing configuration database."""

import hashlib
import time

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.config import GlobalConfig
from app.shared.sensor_catalog import SENSOR_CATALOG, is_custom_sensor


def custom_sensor_definition(name, description, unit=""):
    if not all(isinstance(value, str) for value in (name, description, unit)):
        raise HTTPException(422, "Tên, mô tả và đơn vị cảm biến phải là văn bản.")
    name, description, unit = name.strip(), description.strip(), unit.strip()
    if not 1 <= len(name) <= 80 or not 1 <= len(description) <= 240 or len(unit) > 16 or any(ord(char) < 32 for char in name + description + unit):
        raise HTTPException(422, "Tên tối đa 80 ký tự, mô tả tối đa 240 ký tự và đơn vị tối đa 16 ký tự.")
    if any(row['label'].casefold() == name.casefold() for row in SENSOR_CATALOG.values()):
        raise HTTPException(409, "Tên cảm biến đã có trong danh sách.")
    key = "custom_" + hashlib.sha256(name.casefold().encode()).hexdigest()[:12]
    return {"key": key, "label": name, "group": "Khác", "field": "value", "fields": ["value"],
            "unit": unit, "legacy": False,
            "metrics": [{"field": "value", "label": name, "unit": unit, "decimals": 3}],
            "note": description, "optional_metrics": []}


async def get_custom_sensors(db):
    rows = (await db.execute(select(GlobalConfig).where(GlobalConfig.key.like("custom\\_%", escape="\\"))
                             .order_by(GlobalConfig.id))).scalars().all()
    return [row.value for row in rows if is_custom_sensor(row.key) and isinstance(row.value, dict)]


async def create_custom_sensor(db, name, description, unit=""):
    definition = custom_sensor_definition(name, description, unit)
    key = definition["key"]
    existing = (await db.execute(select(GlobalConfig).where(GlobalConfig.key == key))).scalar_one_or_none()
    if existing:
        if existing.value != definition:
            raise HTTPException(409, "Tên cảm biến đã tồn tại với mô tả hoặc đơn vị khác.")
        return existing.value
    db.add(GlobalConfig(key=key, value=definition, updated_at=int(time.time())))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing = (await db.execute(select(GlobalConfig).where(GlobalConfig.key == key))).scalar_one()
        if existing.value != definition:
            raise HTTPException(409, "Tên cảm biến đã tồn tại với mô tả hoặc đơn vị khác.")
        return existing.value
    return definition


async def validate_custom_sensor_selection(db, sensors, config):
    custom_keys = {key for key in sensors if is_custom_sensor(key)}
    if set(sensors) - set(SENSOR_CATALOG) - custom_keys:
        raise HTTPException(422, "Loại cảm biến không hợp lệ.")
    definitions = config.get("custom_sensors", {}) if isinstance(config, dict) else {}
    if not isinstance(definitions, dict) or set(definitions) != custom_keys:
        raise HTTPException(422, "Danh sách cảm biến tự thêm không khớp cấu hình trạm.")
    if not custom_keys:
        return
    rows = (await db.execute(select(GlobalConfig).where(GlobalConfig.key.in_(custom_keys)))).scalars().all()
    registered = {row.key: row.value for row in rows}
    if any(definitions[key] != registered.get(key) for key in custom_keys):
        raise HTTPException(422, "Cảm biến tự thêm chưa được đăng ký hoặc đã bị sửa.")
