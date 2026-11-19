#backend/processors/water_processor.py
import logging
import json
import re
from collections import deque
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

NUMBER_RE = r"-?\d+(?:\.\d+)?"

class WaterEngine:
    def __init__(self, history_size: int = 36, valid_min: float = 0.0, valid_max: float = 50.0):
        self.history = deque(maxlen=history_size)
        self.valid_min = valid_min
        self.valid_max = valid_max
        self.last_valid_value = 0.0 
        logger.info(f"WaterEngine init: Range [{self.valid_min}m - {self.valid_max}m]")

    def _extract_numeric_value(self, raw_value: Any) -> Optional[float]:
        """Extract a numeric value from scalar/list/string payloads."""
        if raw_value is None:
            return None

        if isinstance(raw_value, (int, float)):
            return float(raw_value)

        if isinstance(raw_value, (list, tuple)):
            if not raw_value:
                return None
            try:
                return float(raw_value[-1])
            except (TypeError, ValueError):
                return None

        if isinstance(raw_value, str):
            text = raw_value.strip()
            if not text:
                return None

            # Common incoming format: "[0, 121]" -> use the latest channel value.
            if text.startswith('[') and text.endswith(']'):
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, list) and parsed:
                        return float(parsed[-1])
                except (TypeError, ValueError):
                    numbers = re.findall(NUMBER_RE, text)
                    if numbers:
                        return float(numbers[-1])

            try:
                return float(text)
            except ValueError:
                numbers = re.findall(NUMBER_RE, text)
                if numbers:
                    return float(numbers[-1])

        return None

    def _to_meters(self, payload: Dict[str, Any], parsed_value: float) -> float:
        """Normalize raw sensor values to meters for internal processing."""
        sensor_type = str(payload.get("sensortype", "")).upper()
        sensor_name = str(payload.get("sensorname", "")).upper()

        # ATG_GWL / GWL: Check if value is already in meters or needs conversion from mm
        if sensor_type == "GWL" or sensor_name == "ATG_GWL":
            # If value < 100, it's likely already in meters
            # If value >= 100, it's in millimeters and needs conversion
            if parsed_value < 100:
                return parsed_value  # Already in meters
            else:
                return parsed_value / 1000.0  # Convert from mm to meters

        # Legacy payloads with explicit key are assumed to already be in meters.
        if payload.get("water_level") is not None:
            return parsed_value

        return parsed_value

    def process(self, payload: Dict[str, Any], timestamp: float) -> Optional[Dict[str, Any]]:
        try:
            sensor_type = str(payload.get("sensortype", "")).upper()
            sensor_name = str(payload.get("sensorname", "")).upper()
            val = payload.get("value")
            if val is None:
                val = payload.get("water_level")
            
            if val is None:
                logger.warning("Water value is None, using last valid value")
                return {
                    "water_level": round(self.last_valid_value, 3),
                    "water_level_cm": round(self.last_valid_value * 100, 2),
                    "water_display_value": round(self.last_valid_value, 3),
                    "water_display_unit": "m",
                    "is_fallback": True
                }

            parsed_value = self._extract_numeric_value(val)
            if parsed_value is None:
                raise ValueError(f"Invalid water value format: {val}")

            is_gwl_sensor = sensor_type == "GWL" or sensor_name == "ATG_GWL"
            value_meters = self._to_meters(payload, parsed_value)
            
            # Determine display value and unit
            # If GWL: check if parsed_value needs conversion; if small (<100), it's already in meters
            if is_gwl_sensor:
                if parsed_value < 100:
                    # Already in meters, display as meters for clarity
                    display_value = value_meters
                    display_unit = "m"
                else:
                    # In millimeters as expected for GWL, display as mm
                    display_value = parsed_value
                    display_unit = "mm"
            else:
                display_value = value_meters
                display_unit = "m"
            
            if not (self.valid_min <= value_meters <= self.valid_max):
                logger.debug(f"Water value {value_meters}m out of range, using last valid")
                return {
                    "water_level": round(self.last_valid_value, 3),
                    "water_level_cm": round(self.last_valid_value * 100, 2),
                    "water_display_value": round(self.last_valid_value, 3),
                    "water_display_unit": "m",
                    "is_fallback": True
                }

            self.last_valid_value = value_meters
            self.history.append((timestamp, value_meters))

            return {
                "water_level": round(value_meters, 3),
                "water_level_cm": round(value_meters * 100, 2),
                "water_display_value": round(display_value, 3),
                "water_display_unit": display_unit,
                "is_fallback": False
            }

        except (ValueError, TypeError) as e:
            logger.exception(f"Error processing water data: {e}")
            return {
                "water_level": round(self.last_valid_value, 3),
                "water_level_cm": round(self.last_valid_value * 100, 2),
                "water_display_value": round(self.last_valid_value, 3),
                "water_display_unit": "m",
                "is_fallback": True
            }

class RainEngine:
    def __init__(self, history_size: int = 60):
        self.history = deque(maxlen=history_size)
        self.last_valid_rainfall = 0.0
        self.last_valid_intensity = 0.0
        logger.info(f"RainEngine init: History size {history_size}")

    def _extract_numeric_value(self, raw_value: Any) -> Optional[float]:
        if raw_value is None:
            return None

        if isinstance(raw_value, (int, float)):
            return float(raw_value)

        if isinstance(raw_value, (list, tuple)):
            if not raw_value:
                return None
            try:
                return float(raw_value[-1])
            except (TypeError, ValueError):
                return None

        if isinstance(raw_value, str):
            text = raw_value.strip()
            if not text:
                return None
            if text.startswith('[') and text.endswith(']'):
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, list) and parsed:
                        return float(parsed[-1])
                except (TypeError, ValueError):
                    numbers = re.findall(NUMBER_RE, text)
                    if numbers:
                        return float(numbers[-1])
            try:
                return float(text)
            except ValueError:
                numbers = re.findall(NUMBER_RE, text)
                if numbers:
                    return float(numbers[-1])

        return None

    def process(self, payload: Dict[str, Any], timestamp: float) -> Optional[Dict[str, Any]]:
        try:
            sensor_type = str(payload.get("sensortype", "")).upper()
            sensor_name = str(payload.get("sensorname", "")).upper()

            intensity_mm_h = 0.0
            rainfall_mm = self.last_valid_rainfall

            # ATG_RSB/RSB gửi intensity trực tiếp qua field value.
            if sensor_type == "RSB" or sensor_name == "ATG_RSB":
                raw_intensity = payload.get("value")
                parsed_intensity = self._extract_numeric_value(raw_intensity)
                if parsed_intensity is None:
                    return {
                        "rainfall_mm": round(self.last_valid_rainfall, 2),
                        "intensity_mm_h": round(self.last_valid_intensity, 2),
                        "is_fallback": True
                    }

                intensity_mm_h = max(0.0, float(parsed_intensity))

                # Ước lượng rainfall tích lũy từ intensity để vẫn hỗ trợ biểu đồ/history.
                if len(self.history) > 0:
                    prev_time, prev_rainfall = self.history[-1]
                    time_diff_sec = timestamp - prev_time
                    if 0 < time_diff_sec < 3600:
                        rainfall_mm = prev_rainfall + (intensity_mm_h * time_diff_sec / 3600.0)
                    else:
                        rainfall_mm = prev_rainfall
                else:
                    rainfall_mm = self.last_valid_rainfall
            else:
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
            logger.exception(f"Error processing rain data: {e}")
            return {
                "rainfall_mm": round(self.last_valid_rainfall, 2),
                "intensity_mm_h": round(self.last_valid_intensity, 2),
                "is_fallback": True
            }