import asyncio
import os
import sys

# Thêm đường dẫn backend vào sys.path để import được các module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.sql import text
from app.database import ConfigSessionLocal, DataSessionLocal

async def reset_database():
    print("⚠️  BẮT ĐẦU RESET TOÀN BỘ CƠ SỞ DỮ LIỆU BẰNG TRUNCATE CASCADE...")
    
    # 1. Xóa dữ liệu trong Config DB
    try:
        async with ConfigSessionLocal() as session:
            print("Đang xóa dữ liệu bảng cấu hình (Config DB)...")
            
            # TRUNCATE CASCADE sẽ xóa sạch toàn bộ các bảng liên quan một cách triệt để
            await session.execute(text("TRUNCATE TABLE projects CASCADE;"))
            await session.execute(text("TRUNCATE TABLE stations CASCADE;"))
            await session.execute(text("TRUNCATE TABLE devices CASCADE;"))
            await session.execute(text("TRUNCATE TABLE pi_devices CASCADE;"))
            
            # Cố gắng xóa users nếu có bảng users
            try:
                await session.execute(text("TRUNCATE TABLE users CASCADE;"))
            except Exception:
                pass
                
            await session.commit()
            print("✅ Xóa xong Config DB!")
    except Exception as e:
        print(f"❌ Lỗi khi xóa Config DB: {e}")

    # 2. Xóa dữ liệu trong Data DB
    try:
        async with DataSessionLocal() as session:
            print("\nĐang xóa dữ liệu cảm biến (Data DB)...")
            
            await session.execute(text("TRUNCATE TABLE sensor_data CASCADE;"))
            await session.execute(text("TRUNCATE TABLE alerts CASCADE;"))
            
            await session.commit()
            print("✅ Xóa xong Data DB!")
    except Exception as e:
        print(f"❌ Lỗi khi xóa Data DB: {e}")

    print("\n🎉 HOÀN TẤT RESET DATABASE!")

if __name__ == "__main__":
    confirm = input("CẢNH BÁO: Lệnh này sẽ XÓA SẠCH DỮ LIỆU. Bạn có chắc chắn không? (y/n): ")
    if confirm.lower() == 'y':
        asyncio.run(reset_database())
    else:
        print("Đã hủy quá trình reset.")
