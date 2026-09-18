"""Shared constants and dependencies for the GNSS processor mixins."""

from __future__ import annotations

import asyncio
import calendar
import logging
import math
import re
import time
from collections import deque
from typing import Any, Dict, Optional

import numpy as np

from ..geodetic import (
    DatumParams,
    VN2000Converter,
    normalize_vn2000_l0_value,
    parse_vn2000_central_meridian,
)

logger = logging.getLogger("processors.gnss_processor")

A_WGS84 = 6378137.0
F_WGS84 = 1 / 298.257223563
E2_WGS84 = 2 * F_WGS84 - F_WGS84**2
GNSS_RUNTIME_STATE_VERSION = 2
GNSS_RUNTIME_STATE_SAVE_INTERVAL_S = 15.0


def haversine_2d(lat1, lon1, lat2, lon2):
    radius_m = 6371000
    lat1_rad, lon1_rad, lat2_rad, lon2_rad = map(
        math.radians, [lat1, lon1, lat2, lon2]
    )
    dlon = lon2_rad - lon1_rad
    dlat = lat2_rad - lat1_rad
    a_val = math.sin(dlat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a_val), math.sqrt(1 - a_val))
    return radius_m * c
