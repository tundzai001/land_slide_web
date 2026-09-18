"""Cross-sensor landslide analysis facade.

Analysis is grouped into shared helpers, velocity, rainfall, windows, tilt,
consensus, displacement, and sensor-alert responsibilities.
"""

from .landslide.alerts import SensorAlertAnalysisMixin
from .landslide.helpers import defaultdict, deque, logger
from .landslide.consensus import ConsensusAnalysisMixin
from .landslide.displacement import DisplacementAnalysisMixin
from .landslide.rainfall import RainfallAnalysisMixin
from .landslide.tilt import TiltAnalysisMixin
from .landslide.velocity import VelocityAnalysisMixin
from .landslide.windows import WindowAnalysisMixin
from .landslide.helpers import AnalyzerCommonMixin


class LandslideAnalyzer(
    AnalyzerCommonMixin,
    VelocityAnalysisMixin,
    RainfallAnalysisMixin,
    WindowAnalysisMixin,
    TiltAnalysisMixin,
    ConsensusAnalysisMixin,
    DisplacementAnalysisMixin,
    SensorAlertAnalysisMixin,
):
    def __init__(self):
        # ✅ Bộ đếm xác nhận cho từng station
        self.alert_counters = defaultdict(lambda: {
            'gnss': {'count': 0, 'last_level': None, 'first_detected': 0.0, 'latched_level': None},
            'rain': {'count': 0, 'last_level': None, 'first_detected': 0.0, 'latched_level': None},
            'water': {'count': 0, 'last_level': None, 'first_detected': 0.0, 'latched_level': None},
            'imu': {'count': 0, 'last_level': None, 'first_detected': 0.0, 'latched_level': None}
        })
        # Lịch sử ngắn hạn để phân biệt trượt thật với jitter GNSS dù fix=4.
        self.gnss_recent_history = defaultdict(lambda: deque(maxlen=120))
        # Chống spam warning config phân loại vận tốc GNSS theo từng trạm.
        self._velocity_config_warn_last_ts = defaultdict(float)


__all__ = ["LandslideAnalyzer"]
