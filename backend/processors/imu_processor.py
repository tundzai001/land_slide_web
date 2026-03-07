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
            "raw_roll": 0.0, "raw_pitch": 0.0, "raw_yaw": 0.0,
            "ax": 0.0, "ay": 0.0, "az": 0.0,
            "total_accel": 0.0,
            "battery": 0.0,
            "status": "unknown"
        }
        
        # ✅ IMU Baseline (Origin) — Giống GNSS Origin Locking
        self.baseline = {"roll": 0.0, "pitch": 0.0, "yaw": 0.0}
        self.origin_locked = False

    def set_baseline(self, roll: float, pitch: float, yaw: float):
        """Đặt baseline manually hoặc từ DB config."""
        self.baseline = {"roll": float(roll), "pitch": float(pitch), "yaw": float(yaw)}
        self.origin_locked = True
        logger.info(f"🎯 [IMU] Baseline set: roll={roll:.2f}°, pitch={pitch:.2f}°, yaw={yaw:.2f}°")

    def _auto_lock_baseline(self, roll: float, pitch: float, yaw: float):
        """Tự động khóa baseline từ tin nhắn đầu tiên."""
        if not self.origin_locked:
            self.baseline = {"roll": roll, "pitch": pitch, "yaw": yaw}
            self.origin_locked = True
            logger.info(f"🎯 [IMU] Auto-locked baseline from first message: roll={roll:.2f}°, pitch={pitch:.2f}°, yaw={yaw:.2f}°")

    def _apply_baseline(self, raw_roll: float, raw_pitch: float, raw_yaw: float) -> dict:
        """Tính delta so với baseline."""
        delta_roll = raw_roll - self.baseline["roll"]
        delta_pitch = raw_pitch - self.baseline["pitch"]
        delta_yaw = raw_yaw - self.baseline["yaw"]
        return {
            "roll": round(delta_roll, 2),
            "pitch": round(delta_pitch, 2),
            "yaw": round(delta_yaw, 2),
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

                    # ✅ Auto-lock baseline nếu chưa có
                    self._auto_lock_baseline(angle_x, angle_y, angle_z)

                    # ✅ Tính delta so với baseline
                    delta = self._apply_baseline(angle_x, angle_y, angle_z)

                    # Tạo kết quả chuẩn hóa
                    result = {
                        # Delta angles (dùng cho alerting)
                        "roll": delta["roll"],
                        "pitch": delta["pitch"],
                        "yaw": delta["yaw"],
                        
                        # Raw angles (góc tuyệt đối, để hiển thị tham khảo)
                        "raw_roll": round(angle_x, 2),
                        "raw_pitch": round(angle_y, 2),
                        "raw_yaw": round(angle_z, 2),
                        
                        # Baseline info
                        "baseline_roll": self.baseline["roll"],
                        "baseline_pitch": self.baseline["pitch"],
                        "baseline_yaw": self.baseline["yaw"],
                        
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
            raw_roll = payload.get('roll')
            raw_pitch = payload.get('pitch')
            raw_yaw = payload.get('yaw')

            if raw_roll is None and total_accel > 0:
                raw_roll = math.degrees(math.atan2(ay, az))
            
            if raw_pitch is None and total_accel > 0:
                raw_pitch = math.degrees(math.atan2(-ax, math.sqrt(ay**2 + az**2)))

            raw_roll = float(raw_roll or 0)
            raw_pitch = float(raw_pitch or 0)
            raw_yaw = float(raw_yaw or 0)

            # Lấy pin (nếu có)
            battery = float(payload.get('battery_voltage') or payload.get('battery') or self.last_valid_data.get('battery', 0.0))

            # ✅ Auto-lock baseline nếu chưa có
            self._auto_lock_baseline(raw_roll, raw_pitch, raw_yaw)

            # ✅ Tính delta so với baseline
            delta = self._apply_baseline(raw_roll, raw_pitch, raw_yaw)

            result = {
                "ax": round(ax, 3), "ay": round(ay, 3), "az": round(az, 3),
                "gx": round(gx, 3), "gy": round(gy, 3), "gz": round(gz, 3),
                # Delta angles (dùng cho alerting)
                "roll": delta["roll"],
                "pitch": delta["pitch"],
                "yaw": delta["yaw"],
                # Raw angles
                "raw_roll": round(raw_roll, 2),
                "raw_pitch": round(raw_pitch, 2),
                "raw_yaw": round(raw_yaw, 2),
                # Baseline
                "baseline_roll": self.baseline["roll"],
                "baseline_pitch": self.baseline["pitch"],
                "baseline_yaw": self.baseline["yaw"],
                "total_accel": round(total_accel, 3),
                "battery": round(battery, 2),
                "status": "normal"
            }
            
            self.last_valid_data = result
            return result

        except Exception as e:
            logger.error(f"Error processing IMU data: {e} | Payload: {payload}")
            return self.last_valid_data.copy()