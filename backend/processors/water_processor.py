#backend/processors/water_processor.py
import logging
from collections import deque
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

class WaterEngine:
    def __init__(self, history_size: int = 36, valid_min: float = 0.0, valid_max: float = 50.0):
        self.history = deque(maxlen=history_size)
        self.valid_min = valid_min
        self.valid_max = valid_max
        self.last_valid_value = 0.0 
        logger.info(f"WaterEngine init: Range [{self.valid_min}m - {self.valid_max}m]")

    def process(self, payload: Dict[str, Any], timestamp: float) -> Optional[Dict[str, Any]]:
        try:
            val = payload.get("value") or payload.get("water_level")
            
            if val is None:
                logger.warning("Water value is None, using last valid value")
                return {
                    "water_level": round(self.last_valid_value, 3),
                    "is_fallback": True
                }

            value_meters = float(val)
            if not (self.valid_min <= value_meters <= self.valid_max):
                logger.debug(f"Water value {value_meters}m out of range, using last valid")
                return {
                    "water_level": round(self.last_valid_value, 3),
                    "is_fallback": True
                }

            self.last_valid_value = value_meters
            self.history.append((timestamp, value_meters))

            return {
                "water_level": round(value_meters, 3),
                "is_fallback": False
            }

        except (ValueError, TypeError) as e:
            logger.error(f"Error processing water data: {e}")
            return {
                "water_level": round(self.last_valid_value, 3),
                "is_fallback": True
            }

class RainEngine:
    def __init__(self, history_size: int = 60):
        self.history = deque(maxlen=history_size)
        self.last_valid_rainfall = 0.0
        self.last_valid_intensity = 0.0
        logger.info(f"RainEngine init: History size {history_size}")

    def process(self, payload: Dict[str, Any], timestamp: float) -> Optional[Dict[str, Any]]:
        try:
            val = payload.get("rainfall_mm")
            if val is None:
                return {
                    "rainfall_mm": round(self.last_valid_rainfall, 2),
                    "intensity_mm_h": round(self.last_valid_intensity, 2),
                    "is_fallback": True
                }
            
            rainfall_mm = float(val)
            
            # 1. Ưu tiên intensity từ thiết bị
            intensity_input = payload.get("intensity_mm_h")
            intensity_mm_h = 0.0

            if intensity_input is not None:
                intensity_mm_h = float(intensity_input)
            
            # 2. Tính toán intensity nếu thiết bị không gửi
            elif len(self.history) > 0:
                prev_time, prev_rainfall = self.history[-1]
                time_diff_sec = timestamp - prev_time
                rainfall_diff_mm = rainfall_mm - prev_rainfall
                
                if 0 < time_diff_sec < 3600 and rainfall_diff_mm >= 0:
                    intensity_mm_h = (rainfall_diff_mm / time_diff_sec) * 3600

            # Lưu giá trị hợp lệ
            self.last_valid_rainfall = rainfall_mm
            self.last_valid_intensity = intensity_mm_h
            self.history.append((timestamp, rainfall_mm))

            return {
                "rainfall_mm": round(rainfall_mm, 2),
                "intensity_mm_h": round(intensity_mm_h, 2),
                "is_fallback": False
            }

        except (ValueError, TypeError) as e:
            logger.error(f"Error processing rain data: {e}")
            return {
                "rainfall_mm": round(self.last_valid_rainfall, 2),
                "intensity_mm_h": round(self.last_valid_intensity, 2),
                "is_fallback": True
            }