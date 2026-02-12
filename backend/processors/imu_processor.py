# backend/processors/imu_processor.py
import logging
import math
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

class IMUEngine:
    def __init__(self):
        # Lưu trữ giá trị gần nhất để fallback nếu mất gói tin
        self.last_valid_data = {
            "roll": 0.0, "pitch": 0.0, "yaw": 0.0,
            "ax": 0.0, "ay": 0.0, "az": 0.0,
            "total_accel": 0.0,
            "battery": 0.0,
            "status": "unknown"
        }

    def process(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            # =================================================================
            # CASE 1: FORMAT MỚI (Inclinometer / Tilt Sensor)
            # JSON: {'angle_xyz': ['-2.2', '-3.8', '4.4'], 'battery_voltage': '3.58', ...}
            # =================================================================
            if 'angle_xyz' in payload and isinstance(payload['angle_xyz'], list):
                angles = payload['angle_xyz']
                
                # Đảm bảo có đủ 3 góc
                if len(angles) >= 3:
                    # Parse dữ liệu từ String sang Float
                    try:
                        angle_x = float(angles[0]) # Góc X -> Roll
                        angle_y = float(angles[1]) # Góc Y -> Pitch
                        angle_z = float(angles[2]) # Góc Z -> Yaw
                        
                        battery = float(payload.get('battery_voltage', 0))
                    except (ValueError, TypeError):
                        logger.error(f"Error parsing values in new format: {payload}")
                        return self.last_valid_data

                    status = payload.get('status', 'unknown')

                    # Tạo kết quả chuẩn hóa
                    result = {
                        "roll": round(angle_x, 2),
                        "pitch": round(angle_y, 2),
                        "yaw": round(angle_z, 2),
                        "battery": round(battery, 2),
                        "status": status,
                        
                        # Các trường raw accel gán bằng 0 vì bản tin này không có raw data
                        "ax": 0.0, "ay": 0.0, "az": 0.0,
                        "gx": 0.0, "gy": 0.0, "gz": 0.0,
                        "total_accel": 0.0, # Không tính toán va đập từ góc nghiêng tĩnh
                        
                        # Giữ lại các trường gốc để debug nếu cần
                        "angle_x": angle_x,
                        "angle_y": angle_y,
                        "angle_z": angle_z
                    }

                    # Cập nhật cache
                    self.last_valid_data = result
                    return result

            # =================================================================
            # CASE 2: FORMAT CŨ (Raw IMU - Accelerometer/Gyroscope)
            # JSON: {'ax': 0.1, 'ay': 0.2, 'az': 9.8, ...}
            # =================================================================
            
            # Lấy giá trị raw hoặc dùng cache
            ax = float(payload.get('ax') or payload.get('accel_x') or self.last_valid_data.get('ax', 0.0))
            ay = float(payload.get('ay') or payload.get('accel_y') or self.last_valid_data.get('ay', 0.0))
            az = float(payload.get('az') or payload.get('accel_z') or self.last_valid_data.get('az', 9.8))

            gx = float(payload.get('gx') or payload.get('gyro_x') or self.last_valid_data.get('gx', 0.0))
            gy = float(payload.get('gy') or payload.get('gyro_y') or self.last_valid_data.get('gy', 0.0))
            gz = float(payload.get('gz') or payload.get('gyro_z') or self.last_valid_data.get('gz', 0.0))

            # Tính toán vector tổng gia tốc (để phát hiện va đập/rung chấn)
            total_accel = math.sqrt(ax**2 + ay**2 + az**2)

            # Tính toán góc từ gia tốc (nếu thiết bị không gửi góc sẵn)
            roll = payload.get('roll')
            pitch = payload.get('pitch')
            yaw = payload.get('yaw')

            if roll is None and total_accel > 0:
                roll = math.degrees(math.atan2(ay, az))
            
            if pitch is None and total_accel > 0:
                pitch = math.degrees(math.atan2(-ax, math.sqrt(ay**2 + az**2)))

            # Lấy pin (nếu có)
            battery = float(payload.get('battery_voltage') or payload.get('battery') or self.last_valid_data.get('battery', 0.0))

            result = {
                "ax": round(ax, 3), "ay": round(ay, 3), "az": round(az, 3),
                "gx": round(gx, 3), "gy": round(gy, 3), "gz": round(gz, 3),
                "roll": round(float(roll or 0), 2),
                "pitch": round(float(pitch or 0), 2),
                "yaw": round(float(yaw or 0), 2),
                "total_accel": round(total_accel, 3),
                "battery": round(battery, 2),
                "status": "normal"
            }
            
            self.last_valid_data = result
            return result

        except Exception as e:
            logger.error(f"Error processing IMU data: {e} | Payload: {payload}")
            return self.last_valid_data.copy()