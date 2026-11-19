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

    def _calculate_drift(self, delta_roll: float, delta_pitch: float, pole_height: float = 90.0) -> tuple:
        """Tính độ lệch tâm (văng) giả định cột cao theo thực tế (mặc định 90mm) bằng phép chiếu không gian."""
        r_rad = math.radians(delta_roll)
        p_rad = math.radians(delta_pitch)
        
        # Để chính xác hơn trong không gian 3D, sự dịch chuyển của ngọn cột độ dài L=1000:
        # Trong hệ tọa độ cầu/Euler, độ lệch tổng được tính dựa trên sin của góc nghiêng
        # Tính góc nghiêng tổng (total tilt angle):
        total_tilt_rad = math.sqrt(r_rad**2 + p_rad**2)
        
        # Khoảng cách lệch (kiểu cung lớn/dây cung) xấp xỉ L * sin(góc) 
        # (vòng về chiếu ngang thay vì chiếu hình học phẳng với tan)
        drift = pole_height * math.sin(total_tilt_rad)
        
        # Phân tích ra dx và dy để xác định hướng (dựa trên tỷ lệ góc)
        dx = pole_height * math.sin(r_rad)
        dy = pole_height * math.sin(p_rad)
        
        dir_text = "--"
        if drift > 0.1:
            angle_deg = math.degrees(math.atan2(dy, dx))
            if angle_deg < 0: angle_deg += 360
            dirs = ["Đ", "ĐB", "B", "TB", "T", "TN", "N", "ĐN"]
            idx = int(round(angle_deg / 45)) % 8
            dir_text = dirs[idx]
        
        return round(drift, 2), dir_text

    def _process_inclinometer(self, payload: Dict[str, Any], pole_height: float) -> Optional[Dict[str, Any]]:
        angles = payload['angle_xyz']
        if len(angles) < 3:
            return None
        try:
            angle_x = float(angles[0])
            angle_y = float(angles[1])
            angle_z = float(angles[2])
            battery = float(payload.get('battery_voltage', 0))
        except (ValueError, TypeError):
            logger.error(f"Error parsing values in new format: {payload}")
            return self.last_valid_data

        status = payload.get('status', 'unknown')
        self._auto_lock_baseline(angle_x, angle_y, angle_z)
        delta = self._apply_baseline(angle_x, angle_y, angle_z)
        drift_len, drift_dir = self._calculate_drift(delta["roll"], delta["pitch"], pole_height)

        result = {
            "roll": delta["roll"], "pitch": delta["pitch"], "yaw": delta["yaw"],
            "drift_len_mm": drift_len, "drift_dir": drift_dir,
            "raw_roll": round(angle_x, 2), "raw_pitch": round(angle_y, 2), "raw_yaw": round(angle_z, 2),
            "baseline_roll": self.baseline["roll"], "baseline_pitch": self.baseline["pitch"], "baseline_yaw": self.baseline["yaw"],
            "battery": round(battery, 2), "status": status,
            "ax": 0.0, "ay": 0.0, "az": 0.0, "gx": 0.0, "gy": 0.0, "gz": 0.0, "total_accel": 0.0,
            "angle_x": angle_x, "angle_y": angle_y, "angle_z": angle_z
        }
        self.last_valid_data = result
        return result

    def _extract_imu_field(self, payload: dict, keys: tuple, default: float) -> float:
        for k in keys:
            val = payload.get(k)
            if val is not None:
                return float(val)
        return default

    def _process_raw_imu(self, payload: Dict[str, Any], pole_height: float) -> Optional[Dict[str, Any]]:
        ax = self._extract_imu_field(payload, ('ax', 'accel_x'), self.last_valid_data.get('ax', 0.0))
        ay = self._extract_imu_field(payload, ('ay', 'accel_y'), self.last_valid_data.get('ay', 0.0))
        az = self._extract_imu_field(payload, ('az', 'accel_z'), self.last_valid_data.get('az', 9.8))
        gx = self._extract_imu_field(payload, ('gx', 'gyro_x'), self.last_valid_data.get('gx', 0.0))
        gy = self._extract_imu_field(payload, ('gy', 'gyro_y'), self.last_valid_data.get('gy', 0.0))
        gz = self._extract_imu_field(payload, ('gz', 'gyro_z'), self.last_valid_data.get('gz', 0.0))

        total_accel = math.sqrt(ax**2 + ay**2 + az**2)
        raw_roll = payload.get('roll')
        raw_pitch = payload.get('pitch')
        raw_yaw = float(payload.get('yaw') or 0)
        if raw_roll is None and total_accel > 0:
            raw_roll = math.degrees(math.atan2(ay, az))
        if raw_pitch is None and total_accel > 0:
            raw_pitch = math.degrees(math.atan2(-ax, math.sqrt(ay**2 + az**2)))

        raw_roll = float(raw_roll or 0)
        raw_pitch = float(raw_pitch or 0)
        battery = self._extract_imu_field(payload, ('battery_voltage', 'battery'), self.last_valid_data.get('battery', 0.0))

        self._auto_lock_baseline(raw_roll, raw_pitch, raw_yaw)
        delta = self._apply_baseline(raw_roll, raw_pitch, raw_yaw)
        drift_len, drift_dir = self._calculate_drift(delta["roll"], delta["pitch"], pole_height)

        result = {
            "ax": round(ax, 3), "ay": round(ay, 3), "az": round(az, 3),
            "gx": round(gx, 3), "gy": round(gy, 3), "gz": round(gz, 3),
            "roll": delta["roll"], "pitch": delta["pitch"], "yaw": delta["yaw"],
            "drift_len_mm": drift_len, "drift_dir": drift_dir,
            "raw_roll": round(raw_roll, 2), "raw_pitch": round(raw_pitch, 2), "raw_yaw": round(raw_yaw, 2),
            "baseline_roll": self.baseline["roll"], "baseline_pitch": self.baseline["pitch"], "baseline_yaw": self.baseline["yaw"],
            "total_accel": round(total_accel, 3), "battery": round(battery, 2), "status": "normal"
        }
        self.last_valid_data = result
        return result

    def process(self, payload: Dict[str, Any], station_config: Dict = None) -> Optional[Dict[str, Any]]:
        pole_height = 90.0
        if station_config:
            imu_cfg = station_config.get('imu_alerting', {})
            pole_height = float(imu_cfg.get('pole_height_mm', 90.0))
            
        try:
            if 'angle_xyz' in payload and isinstance(payload['angle_xyz'], list):
                res = self._process_inclinometer(payload, pole_height)
                if res is not None:
                    return res
            return self._process_raw_imu(payload, pole_height)
        except Exception as e:
            logger.exception(f"Error processing IMU data: {e} | Payload: {payload}")
            return self.last_valid_data.copy()
