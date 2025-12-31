#backend/processors/imu_processor.py
import logging
import math
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

class IMUEngine:
    def __init__(self):
        self.last_valid_data = {
            "ax": 0.0, "ay": 0.0, "az": 9.8,
            "gx": 0.0, "gy": 0.0, "gz": 0.0,
            "roll": 0.0, "pitch": 0.0, "yaw": 0.0,
            "total_accel": 9.8
        }

    def process(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            # 1. Trích xuất với giá trị mặc định an toàn
            ax = float(payload.get('ax') or payload.get('accel_x') or self.last_valid_data['ax'])
            ay = float(payload.get('ay') or payload.get('accel_y') or self.last_valid_data['ay'])
            az = float(payload.get('az') or payload.get('accel_z') or self.last_valid_data['az'])

            gx = float(payload.get('gx') or payload.get('gyro_x') or self.last_valid_data['gx'])
            gy = float(payload.get('gy') or payload.get('gyro_y') or self.last_valid_data['gy'])
            gz = float(payload.get('gz') or payload.get('gyro_z') or self.last_valid_data['gz'])

            # 2. Tính total acceleration
            total_accel = math.sqrt(ax**2 + ay**2 + az**2)

            # 3. Tính roll/pitch từ accel nếu không có sẵn
            roll = payload.get('roll')
            pitch = payload.get('pitch')
            yaw = payload.get('yaw')

            if roll is None and total_accel > 0:
                roll = math.degrees(math.atan2(ay, az))
            
            if pitch is None and total_accel > 0:
                pitch = math.degrees(math.atan2(-ax, math.sqrt(ay**2 + az**2)))

            # ✅ Đảm bảo tất cả giá trị đều là số (không None)
            roll = float(roll) if roll is not None else self.last_valid_data['roll']
            pitch = float(pitch) if pitch is not None else self.last_valid_data['pitch']
            yaw = float(yaw) if yaw is not None else self.last_valid_data['yaw']

            # 4. Lưu giá trị hợp lệ
            result = {
                "ax": round(ax, 3), "ay": round(ay, 3), "az": round(az, 3),
                "gx": round(gx, 3), "gy": round(gy, 3), "gz": round(gz, 3),
                "roll": round(roll, 2),
                "pitch": round(pitch, 2),
                "yaw": round(yaw, 2),
                "total_accel": round(total_accel, 3)
            }
            
            self.last_valid_data = result
            return result

        except (ValueError, TypeError) as e:
            logger.error(f"Error processing IMU data: {e}")
            # ✅ Trả về giá trị cuối cùng thay vì None
            return self.last_valid_data.copy()