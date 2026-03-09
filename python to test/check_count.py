# backend/check_count.py
import asyncio
import sys
import os
from sqlalchemy import select, func

# Thêm đường dẫn để import được app
sys.path.append(os.getcwd())

from app.database import DataSessionLocal
from app.models.data import SensorData

async def check_database_status():
    print("\n" + "="*50)
    print("🕵️  KIỂM TRA DỮ LIỆU SENSOR_DATA")
    print("="*50)
    
    try:
        async with DataSessionLocal() as db:
            # 1. Đếm tổng số dòng
            count_query = select(func.count()).select_from(SensorData)
            total = await db.execute(count_query)
            total_count = total.scalar()
            
            # 2. Tìm ID nhỏ nhất (Min ID)
            min_query = select(func.min(SensorData.id))
            min_res = await db.execute(min_query)
            min_id = min_res.scalar()
            
            # 3. Tìm ID lớn nhất (Max ID)
            max_query = select(func.max(SensorData.id))
            max_res = await db.execute(max_query)
            max_id = max_res.scalar()
            
            print(f"📊 Tổng số bản ghi hiện có: {total_count:,} dòng")
            print(f"🔹 ID nhỏ nhất (Min ID):    {min_id}")
            print(f"🔸 ID lớn nhất (Max ID):    {max_id}")
            print("-" * 50)
            
            if min_id and min_id > 1:
                print(f"⚠️  KẾT LUẬN: Các bản ghi từ ID 1 đến {min_id - 1} ĐÃ BỊ XÓA.")
                print("   (Do cơ chế Auto-Increment, ID sẽ không bao giờ được cấp lại)")
            elif min_id == 1:
                print("✅ KẾT LUẬN: Dữ liệu còn nguyên vẹn từ ID 1.")
            else:
                print("⚠️  Database đang trống.")

    except Exception as e:
        print(f"❌ Lỗi: {e}")
    print("="*50 + "\n")

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(check_database_status())