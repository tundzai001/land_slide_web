
import asyncio
import os
import sys
from datetime import datetime

# Set path to backend
sys.path.append(os.path.abspath('.'))

from app.database import DataSessionLocal
from app.models.data import SensorData
from sqlalchemy import select

async def check_data():
    print("Checking Database for ST25 data...")
    async with DataSessionLocal() as db:
        # Check overall latest data
        res = await db.execute(select(SensorData).order_by(SensorData.timestamp.desc()).limit(10))
        rows = res.scalars().all()
        if not rows:
            print("No sensor data found in DB.")
        else:
            print(f"Found {len(rows)} recent records:")
            for r in rows:
                dt = datetime.fromtimestamp(r.timestamp)
                print(f"TS: {r.timestamp} ({dt}), Type: {r.sensor_type}, Station: {r.station_id}")
        
        # Check specific station ST25 (station_id 25?)
        # Need to check station ID from config DB first?
        # Let's just find records for any station that matches ST25 in some field.
        # Actually I'll just check if any station is active.

if __name__ == "__main__":
    asyncio.run(check_data())
