"""AnalyzerCommonMixin for cross-sensor landslide analysis."""

from __future__ import annotations

import logging
import math
import time
from collections import OrderedDict, defaultdict, deque
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger("processors.landslide_analyzer")


class AnalyzerCommonMixin:
    def _as_bool(self, value: Any, default: bool = True) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            v = value.strip().lower()
            if v in ('1', 'true', 'yes', 'on'):
                return True
            if v in ('0', 'false', 'no', 'off'):
                return False
        return default

    def _get_cfg(self, config: Dict, section: str, key: str, default: float) -> float:
        try:
            raw = config.get(section, {}).get(key, default)
            if isinstance(raw, str):
                raw = raw.strip().replace(',', '.')
            return float(raw)
        except (ValueError, TypeError, AttributeError):
            return float(default)

    def _get_gnss_min_reliable_window_days(self, config: Dict) -> float:
        min_hours = self._get_cfg(config, "GnssAlerting", "longterm_min_duration_hours", 1.0)
        return max(min_hours / 24.0, 1.0 / 1440.0)

    def _is_reliable_observation_window(
        self,
        duration_days: float,
        data_points: int,
        min_duration_days: float,
        min_points: int = 3
    ) -> bool:
        return duration_days >= min_duration_days and data_points >= min_points

    def _build_gnss_preliminary_message(
        self,
        duration_days: float,
        data_points: int,
        min_duration_days: float,
        min_points: int = 3
    ) -> str:
        observed_minutes = max(duration_days * 1440.0, 0.0)
        required_minutes = max(min_duration_days * 1440.0, 1.0)
        return (
            f"Chưa đủ thời lượng để kết luận vận tốc GNSS dài hạn: "
            f"cần >= {required_minutes:.0f} phút và >= {min_points} điểm, "
            f"hiện có {observed_minutes:.0f} phút và {data_points} điểm."
        )

    def _filter_outliers_iqr(self, data_points: List[Dict], field: str = 'pos_e') -> List[Dict]:
        """Loại bỏ outlier bằng IQR trên trường pos_e/pos_n/pos_u."""
        if len(data_points) < 4:
            return data_points

        values = np.array([p['data'].get(field, 0) for p in data_points])
        q1, q3 = np.percentile(values, [25, 75])
        iqr = q3 - q1
        lower = q1 - 3.0 * iqr
        upper = q3 + 3.0 * iqr

        filtered = []
        for i, p in enumerate(data_points):
            v = values[i]
            if lower <= v <= upper:
                filtered.append(p)

        removed = len(data_points) - len(filtered)
        if removed > 0:
            logger.info(f"🧹 Outlier filter ({field}): removed {removed}/{len(data_points)} points")
        return filtered

    def _filter_gnss_quality(self, data_points: List[Dict], min_fix: int = 4) -> List[Dict]:
        """Lọc dữ liệu GNSS theo chất lượng fix (RTK Fixed = 4+)."""
        filtered = [
            p for p in data_points
            if p['data'].get('fix_quality', min_fix) >= min_fix
        ]
        removed = len(data_points) - len(filtered)
        if removed > 0:
            logger.info(f"🛰️ Quality filter: removed {removed}/{len(data_points)} low-quality fixes")
        return filtered if len(filtered) >= 2 else data_points
