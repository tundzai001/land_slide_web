"""SensorAlertAnalysisMixin for cross-sensor landslide analysis."""

from __future__ import annotations

from .helpers import Any, Dict, List, Optional, OrderedDict, datetime, defaultdict, deque, logger, math, np, time


class SensorAlertAnalysisMixin:
    def analyze_rainfall(self, station_id: int, recent_data: List[Dict], _past_72h: List[Dict], config: Dict) -> Optional[Dict]:
        if not recent_data: return None
        try:
            watch = self._get_cfg(config, 'RainAlerting', 'rain_intensity_watch_threshold', 10.0)
            warning = self._get_cfg(config, 'RainAlerting', 'rain_intensity_warning_threshold', 25.0)
            critical = self._get_cfg(config, 'RainAlerting', 'rain_intensity_critical_threshold', 50.0)
            warning_confirm_steps = int(config.get('RainAlerting', {}).get('rain_warning_confirm_steps', config.get('RainAlerting', {}).get('rain_confirm_steps', 2)))
            critical_confirm_steps = int(config.get('RainAlerting', {}).get('rain_critical_confirm_steps', config.get('RainAlerting', {}).get('rain_confirm_steps', 1)))
            safe_confirm_steps = int(config.get('RainAlerting', {}).get('rain_safe_confirm_steps', 3))

            intensity = recent_data[-1]['data'].get('intensity_mm_h', 0.0)

            current_level = "INFO"
            if intensity >= critical: current_level = "CRITICAL"
            elif intensity >= warning: current_level = "WARNING"
            elif intensity >= watch: current_level = "INFO"

            counter_info = self.alert_counters[station_id]['rain']
            if 'latched_level' not in counter_info:
                counter_info['latched_level'] = None
            if 'safe_count' not in counter_info:
                counter_info['safe_count'] = 0

            if current_level in ["WARNING", "CRITICAL"]:
                required_steps = critical_confirm_steps if current_level == "CRITICAL" else warning_confirm_steps
                counter_info['safe_count'] = 0
                if counter_info['latched_level'] == current_level:
                    return {'level': 'PENDING', 'category': 'rainfall'}
                if counter_info['last_level'] != current_level:
                    counter_info['count'] = 1
                    counter_info['last_level'] = current_level
                    return None
                else:
                    counter_info['count'] += 1
                    if counter_info['count'] >= required_steps:
                        counter_info['latched_level'] = current_level
                        counter_info['latched_time'] = time.time()  # Ghi timestamp
                        logger.warning(f"🌧️ [RAIN-{station_id}] ✅ CONFIRMED {current_level}")
                        audio_code = "rain_warning"
                        if current_level == "CRITICAL":
                            audio_code = "rain_critical"
                        return {"level": current_level, "category": "rainfall", "message": f"Mưa lớn: {intensity:.1f}mm/h", "audio_code": audio_code, "details": {"val": intensity}}
                    return None
            else:
                if counter_info['latched_level'] is not None:
                    latched_time = counter_info.get('latched_time', time.time())
                    elapsed = time.time() - latched_time
                    if elapsed > 900:  # 15 phút
                        logger.warning(f"🔄 [RAIN-{station_id}] Timeout auto-reset: {elapsed:.0f}s latched, now safe")
                        counter_info['count'] = 0
                        counter_info['safe_count'] = 0
                        counter_info['last_level'] = None
                        counter_info['latched_level'] = None
                        return None
                    counter_info['safe_count'] += 1
                    if counter_info['safe_count'] < safe_confirm_steps:
                        return {'level': 'PENDING'}
                    counter_info['count'] = 0
                    counter_info['safe_count'] = 0
                    counter_info['last_level'] = None
                    counter_info['latched_level'] = None
                else:
                    counter_info['count'] = max(0, counter_info['count'] - 1)
                    if counter_info['count'] == 0:
                        counter_info['last_level'] = None

            return None
        except Exception as e:
            logger.error(f"Error analyzing RAIN for station {station_id}: {e}", exc_info=True)
            return None

    def analyze_water_level(self, station_id: int, recent_data: List[Dict], config: Dict) -> Optional[Dict]:
        if not recent_data: return None
        try:
            val = recent_data[-1]['data'].get('water_level', 0.0)
            warn = self._get_cfg(config, 'Water', 'warning_threshold', 999.0)
            crit = self._get_cfg(config, 'Water', 'critical_threshold', 999.0)
            warning_confirm_steps = int(config.get('Water', {}).get('water_warning_confirm_steps', config.get('Water', {}).get('water_confirm_steps', 3)))
            critical_confirm_steps = int(config.get('Water', {}).get('water_critical_confirm_steps', config.get('Water', {}).get('water_confirm_steps', 2)))
            safe_confirm_steps = int(config.get('Water', {}).get('water_safe_confirm_steps', 3))

            current_level = "INFO"
            if val >= crit: current_level = "CRITICAL"
            elif val >= warn: current_level = "WARNING"

            counter_info = self.alert_counters[station_id]['water']
            if 'latched_level' not in counter_info:
                counter_info['latched_level'] = None
            if 'safe_count' not in counter_info:
                counter_info['safe_count'] = 0

            if current_level in ["WARNING", "CRITICAL"]:
                required_steps = critical_confirm_steps if current_level == "CRITICAL" else warning_confirm_steps
                counter_info['safe_count'] = 0
                if counter_info['latched_level'] == current_level:
                    return {'level': 'PENDING', 'category': 'water_level'}
                if counter_info['last_level'] != current_level:
                    counter_info['count'] = 1
                    counter_info['last_level'] = current_level
                    return None
                else:
                    counter_info['count'] += 1
                    if counter_info['count'] >= required_steps:
                        counter_info['latched_level'] = current_level
                        counter_info['latched_time'] = time.time()  # Ghi timestamp
                        logger.warning(
                            f"💧 [WATER-{station_id}] ✅ CONFIRMED {current_level} "
                            f"(value={val:.3f}m, warn={warn:.3f}m, crit={crit:.3f}m)"
                        )
                        audio_code = "water_warning"
                        if current_level == "CRITICAL":
                            audio_code = "water_critical"
                        threshold_ref = crit if current_level == "CRITICAL" else warn
                        return {
                            "level": current_level,
                            "category": "water_level",
                            "message": f"Nước cao: {val:.2f}m (ngưỡng {current_level}: {threshold_ref:.2f}m)",
                            "audio_code": audio_code,
                            "details": {
                                "val": val,
                                "warning_threshold": warn,
                                "critical_threshold": crit,
                            }
                        }
                    return None
            else:
                if counter_info['latched_level'] is not None:
                    latched_time = counter_info.get('latched_time', time.time())
                    elapsed = time.time() - latched_time
                    if elapsed > 900:  # 15 phút
                        logger.warning(f"🔄 [WATER-{station_id}] Timeout auto-reset: {elapsed:.0f}s latched, now safe")
                        counter_info['count'] = 0
                        counter_info['safe_count'] = 0
                        counter_info['last_level'] = None
                        counter_info['latched_level'] = None
                        return None
                    counter_info['safe_count'] += 1
                    if counter_info['safe_count'] < safe_confirm_steps:
                        return {'level': 'PENDING'}
                    counter_info['count'] = 0
                    counter_info['safe_count'] = 0
                    counter_info['last_level'] = None
                    counter_info['latched_level'] = None
                else:
                    counter_info['count'] = max(0, counter_info['count'] - 1)
                    if counter_info['count'] == 0:
                        counter_info['last_level'] = None

            return None
        except Exception as e:
            logger.error(f"Error analyzing WATER for station {station_id}: {e}", exc_info=True)
            return None

    def analyze_tilt(self, station_id: int, recent_data: List[Dict], config: Dict) -> Optional[Dict]:
        if not recent_data: return None
        try:
            latest = recent_data[-1]['data']
            
            # Góc nghiêng
            roll = latest.get('roll', 0.0)
            pitch = latest.get('pitch', 0.0)
            delta_tilt = math.sqrt(roll**2 + pitch**2)
            
            tilt_crit = self._get_cfg(config, 'ImuAlerting', 'tilt_critical_deg', 15.0)
            
            # Va đập
            accel = latest.get('total_accel', 0.0)
            shock_thresh = self._get_cfg(config, 'ImuAlerting', 'shock_threshold_ms2', 20.0)
            
            critical_confirm_steps = int(config.get('ImuAlerting', {}).get('imu_critical_confirm_steps', config.get('ImuAlerting', {}).get('imu_confirm_steps', 1)))
            safe_confirm_steps = int(config.get('ImuAlerting', {}).get('imu_safe_confirm_steps', 3))

            # Xác định mức nguy hiểm cao nhất hiện tại
            current_level = "INFO"
            alert_category = "tilt"
            alert_msg = ""
            audio_code = ""
            details = {"delta_tilt_deg": delta_tilt}
            
            # 1. Ưu tiên kiểm tra va đập (Shock) -> thường là CRITICAL ngay
            if accel >= shock_thresh:
                current_level = "CRITICAL"
                alert_category = "shock"
                alert_msg = f"Va đập: {accel:.1f} m/s²"
                audio_code = "imu_shock"
                details["shock_ms2"] = accel
                # Shock có thể cần báo ngay lập tức
                critical_confirm_steps = 1
                
            # 2. Xử lý độ nghiêng (Tilt)
            elif delta_tilt >= tilt_crit:
                current_level = "CRITICAL"
                alert_category = "tilt_critical"
                alert_msg = f"Nghiêng nguy hiểm: {delta_tilt:.1f}°"
                audio_code = "imu_critical"
            
            counter_info = self.alert_counters[station_id]['imu']
            if 'latched_level' not in counter_info:
                counter_info['latched_level'] = None
            if 'safe_count' not in counter_info:
                counter_info['safe_count'] = 0

            if current_level in ["WARNING", "CRITICAL"]:
                required_steps = critical_confirm_steps
                counter_info['safe_count'] = 0
                if counter_info['latched_level'] == current_level:
                    return {'level': 'PENDING', 'category': alert_category}
                if counter_info['last_level'] != current_level:
                    counter_info['count'] = 1
                    counter_info['last_level'] = current_level
                    if counter_info['count'] >= required_steps:
                        counter_info['latched_level'] = current_level
                        logger.warning(f"⚡ [IMU-{station_id}] ✅ CONFIRMED {current_level} ({alert_category})")
                        return {"level": current_level, "category": alert_category, "message": alert_msg, "audio_code": audio_code, "details": details}
                    else:
                        logger.info(f"⏳ [IMU-{station_id}] WAITING CONFIRMATION {current_level} (1/{required_steps})")
                        return {"level": "PENDING", "category": alert_category}
                else:
                    counter_info['count'] += 1
                    if counter_info['count'] >= required_steps:
                        counter_info['latched_level'] = current_level
                        counter_info['latched_time'] = time.time()  # Ghi timestamp
                        logger.warning(f"⚡ [IMU-{station_id}] ✅ CONFIRMED {current_level} ({alert_category}) after {required_steps} times")
                        return {"level": current_level, "category": alert_category, "message": alert_msg, "audio_code": audio_code, "details": details}
                    else:
                        logger.info(f"⏳ [IMU-{station_id}] WAITING CONFIRMATION {current_level} ({counter_info['count']}/{required_steps})")
                        return {"level": "PENDING", "category": alert_category}
            else:
                if counter_info['latched_level'] is not None:
                    latched_time = counter_info.get('latched_time', time.time())
                    elapsed = time.time() - latched_time
                    if elapsed > 900:  # 15 phút
                        logger.warning(f"🔄 [IMU-{station_id}] Timeout auto-reset: {elapsed:.0f}s latched, now safe")
                        counter_info['count'] = 0
                        counter_info['safe_count'] = 0
                        counter_info['last_level'] = None
                        counter_info['latched_level'] = None
                        return None
                    counter_info['safe_count'] += 1
                    logger.debug(f"[IMU-{station_id}] Safe confirm: {counter_info['safe_count']}/{safe_confirm_steps} (was {counter_info['latched_level']})")
                    if counter_info['safe_count'] < safe_confirm_steps:
                        return {'level': 'PENDING'}
                    logger.info(f"✅ [IMU-{station_id}] Confirmed safe after {counter_info['safe_count']} readings")
                    counter_info['count'] = 0
                    counter_info['safe_count'] = 0
                    counter_info['last_level'] = None
                    counter_info['latched_level'] = None
                else:
                    counter_info['count'] = max(0, counter_info['count'] - 1)
                    if counter_info['count'] == 0:
                        counter_info['last_level'] = None

            return None
        except Exception as e:
            logger.error(f"Error analyzing IMU for station {station_id}: {e}", exc_info=True)
            return None
