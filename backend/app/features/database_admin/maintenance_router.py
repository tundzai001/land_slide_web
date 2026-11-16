"""Admin API routes owned by this feature."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from ... import auth
from ...database import get_config_db, get_data_db
from ...models import auth as model_auth
from ...models import data as model_data


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["Admin Console"])



@router.post("/db/clear-table/{table_name}")
async def clear_specific_table(
    table_name: str,
    _config_db: AsyncSession = Depends(get_config_db),
    data_db: AsyncSession = Depends(get_data_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    """
    ✅ Xóa dữ liệu của 1 bảng cụ thể
    Hỗ trợ: sensor_data, alerts
    """
    try:
        if current_user.role != 'admin':
            raise HTTPException(status_code=403, detail="Only admin")

        if table_name == 'sensor_data':
            count = await data_db.execute(text("SELECT COUNT(*) FROM sensor_data"))
            await data_db.execute(delete(model_data.SensorData))

        elif table_name == 'alerts':
            count = await data_db.execute(text("SELECT COUNT(*) FROM alerts"))
            await data_db.execute(delete(model_data.Alert))

        else:
            raise HTTPException(status_code=400, detail="Table not supported")

        await data_db.commit()

        deleted = count.scalar()
        logger.warning(f"⚠️ Table {table_name} cleared: {deleted} records")

        return {
            "status": "success",
            "table": table_name,
            "deleted_count": deleted
        }

    except HTTPException:
        raise
    except Exception as e:
        await data_db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/db/factory-reset")
async def factory_reset_database(
    config_db: AsyncSession = Depends(get_config_db),
    data_db: AsyncSession = Depends(get_data_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    """
    🧨 NGUY HIỂM: XÓA TOÀN BỘ HỆ THỐNG (Project, Station, Device, Data...)
    ID sẽ quay về 1. Chỉ giữ lại User admin.
    """
    try:
        if current_user.role != 'admin':
            raise HTTPException(status_code=403, detail="Only admin")

        # 1. Xóa Data DB (Sensor, Alert)
        await data_db.execute(text("TRUNCATE TABLE sensor_data, alerts RESTART IDENTITY CASCADE"))
        await data_db.commit()

        # 2. Xóa Config DB (Project, Station, Device...)
        # Thứ tự quan trọng: Xóa bảng con trước hoặc dùng CASCADE
        # gnss_origins phụ thuộc devices -> devices phụ thuộc stations -> stations phụ thuộc projects
        await config_db.execute(text("TRUNCATE TABLE gnss_origins, devices, stations, projects RESTART IDENTITY CASCADE"))
        # Keep global_configs because other server-managed metadata may use it.
        await config_db.commit()

        logger.critical(f"🧨 FACTORY RESET executed by {current_user.username}")

        return {
            "status": "success",
            "message": "Hệ thống đã được reset về trạng thái ban đầu (ID = 1). Hãy tạo Dự án mới."
        }

    except HTTPException:
        raise
    except Exception as e:
        await _config_db.rollback()
        await data_db.rollback()


@router.post("/db/clear-all")
async def clear_all_database(
    _config_db: AsyncSession = Depends(get_config_db),
    data_db: AsyncSession = Depends(get_data_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    """
    ✅ XÓA TOÀN BỘ dữ liệu trong Data DB
    Chỉ xóa sensor_data và alerts, GIỮ LẠI stations & devices
    """
    try:
        # ⚠️ NGUY HIỂM: Chỉ dành cho Admin
        if current_user.role != 'admin':
            raise HTTPException(status_code=403, detail="Only admin can clear database")

        # Sử dụng TRUNCATE để xóa nhanh và reset sequence (ID) về 1
        await data_db.execute(text("TRUNCATE TABLE sensor_data, alerts RESTART IDENTITY CASCADE"))
        await data_db.commit()

        logger.warning(f"⚠️ Data Database TRUNCATED by {current_user.username}")

        return {
            "status": "success",
            "message": "Đã xóa sạch dữ liệu cảm biến và Reset ID về 1."
        }

    except HTTPException:
        raise
    except Exception as e:
        await data_db.rollback()
        logger.error(f"❌ Clear database error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
