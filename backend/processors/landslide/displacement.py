"""DisplacementAnalysisMixin for cross-sensor landslide analysis."""

from __future__ import annotations

from .helpers import Any, Dict, List, Optional, OrderedDict, datetime, defaultdict, deque, logger, math, np, time


class DisplacementAnalysisMixin:
    def analyze_gnss_displacement(
        self, 
        station_id: int, 
        recent_data: List[Dict[str, Any]], 
        config: Dict
    ) -> Optional[Dict]:
        
        if not recent_data: return None
        
        try:
            gnss_config = config.get('GnssAlerting', {}) if isinstance(config, dict) else {}
            gnss_enabled = self._as_bool(gnss_config.get('enabled', True), default=True)
            if not gnss_enabled:
                return None

            latest = recent_data[-1]['data']
            # A processor status is evidence about measurement quality, not a
            # safe velocity.  In particular, a restored GNSS quarantine or a
            # post-restart velocity warm-up must never fall through to
            # ``speed_2d=0`` and auto-resolve a durable alert.
            latest_status = str(latest.get('status') or '').upper()
            if latest_status in {
                'INITIALIZING',
                'VELOCITY_WARMUP',
                'UNVERIFIED_POSITION_SHIFT',
                'PERSISTENT_OFFSET_QUARANTINED',
                'REJECTED_MEASUREMENT',
                'UNSTABLE_FIX',
                'REFERENCE_CHANGE_PENDING',
                'STALE_REFERENCE',
                'REACQUIRE_REFUSED',
                'INVALID_DATA',
                'UNTRUSTED_GEOMETRY',
                'CHECKSUM_FAILED',
                'NO_DATA',
            }:
                return {
                    'level': 'PENDING',
                    'category': 'gnss_velocity',
                    'signal_state': 'UNKNOWN',
                    'processor_status': latest_status,
                }
            if latest.get('velocity_reliable') is False:
                return {'level': 'PENDING', 'category': 'gnss_velocity'}
            # New processor payloads separate a statistically significant
            # rolling-window estimate from movement confirmed across windows.
            # Keep the old fallback for payloads produced before that field
            # existed.
            if 'velocity_confirmed' in latest:
                if latest.get('velocity_confirmed') is not True:
                    return {'level': 'PENDING', 'category': 'gnss_velocity'}
            elif latest.get('velocity_significant') is False:
                return {'level': 'PENDING', 'category': 'gnss_velocity'}
            velocity_ms = latest.get('speed_2d', 0.0) 
            velocity_mms = velocity_ms * 1000.0
            
            # Lấy cấu hình xác nhận
            warning_confirm_steps = int(gnss_config.get('gnss_warning_confirm_steps', gnss_config.get('gnss_confirm_steps', 3)))
            critical_confirm_steps = int(gnss_config.get('gnss_critical_confirm_steps', gnss_config.get('gnss_confirm_steps', 2)))
            # Dù đủ confirm_steps, phải span ít nhất X giây liên tục.
            # Ngăn data burst 30Hz confirm trong <200ms.
            min_confirm_seconds = float(gnss_config.get('gnss_confirm_min_seconds', 3.0))
            # Số lần an toàn liên tiếp cần đủ để tự động resolve alert đang active.
            safe_confirm_steps = int(gnss_config.get('gnss_safe_confirm_steps', 5))
            
            velocity_class = self._classify_velocity_extended(
                velocity_mms,
                velocity_mms * 86400,
                velocity_mms * 31536000,
                config,
                station_id=station_id
            )
            
            cls_upper = velocity_class.upper()
            
            # ✅ XÁC ĐỊNH MỨC ĐỘ NGUY HIỂM (chưa gửi alert)
            current_level = "INFO"
            if "EXTREMELY RAPID" in cls_upper or "VERY RAPID" in cls_upper or "RAPID" in cls_upper:
                current_level = "CRITICAL"
            elif "MODERATE" in cls_upper:
                current_level = "WARNING"
            else:
                current_level = "INFO"
            
            # ✅ LẤY BỘ ĐẾM CỦA TRẠM NÀY
            counter_info = self.alert_counters[station_id]['gnss']
            # Backward-compatible for running workers created before latched_level was added.
            if 'latched_level' not in counter_info:
                counter_info['latched_level'] = None
            if 'safe_count' not in counter_info:
                counter_info['safe_count'] = 0

            # Anti-jitter gate tự thích nghi theo noise nền của chính trạm.
            # Không cần set tham số theo từng nơi: nếu chỉ rung quanh 1 điểm,
            # net displacement sẽ nhỏ so với noise envelope và bị hạ về INFO.
            history = self.gnss_recent_history[station_id]
            sample_ts = float(recent_data[-1].get('timestamp', 0.0) or 0.0)
            pos_e = latest.get('pos_e')
            pos_n = latest.get('pos_n')
            pos_u = latest.get('pos_u', 0.0)
            if pos_e is not None and pos_n is not None and sample_ts > 0:
                history.append({'ts': sample_ts, 'e': float(pos_e), 'n': float(pos_n), 'u': float(pos_u or 0.0)})

            if current_level in ["WARNING", "CRITICAL"] and len(history) >= 4:
                motion_points = list(history)
                if counter_info.get('first_detected', 0.0) > 0:
                    recent_motion = [p for p in history if p['ts'] >= counter_info['first_detected']]
                    if len(recent_motion) >= 4:
                        motion_points = recent_motion

                if len(motion_points) >= 4:
                    step_lengths = []
                    for i in range(1, len(motion_points)):
                        dx = motion_points[i]['e'] - motion_points[i - 1]['e']
                        dy = motion_points[i]['n'] - motion_points[i - 1]['n']
                        du = motion_points[i].get('u', 0.0) - motion_points[i - 1].get('u', 0.0)
                        step_lengths.append(math.sqrt(dx * dx + dy * dy + du * du))

                    if len(step_lengths) >= 3:
                        first = motion_points[0]
                        last = motion_points[-1]
                        de = last['e'] - first['e']
                        dn = last['n'] - first['n']
                        du = last.get('u', 0.0) - first.get('u', 0.0)
                        net_m = math.sqrt(de * de + dn * dn + du * du)
                        path_m = float(sum(step_lengths))

                        step_array = np.array(step_lengths, dtype=float)
                        median_step = float(np.median(step_array))
                        mad_step = float(np.median(np.abs(step_array - median_step)))
                        noise_envelope_m = max(median_step + 1.4826 * mad_step, 1e-6)
                        motion_significance = net_m / noise_envelope_m
                        directionality = net_m / max(path_m, 1e-9)

                        # Chỉ suppress khi vừa net displacement 3D nhỏ so với noise floor,
                        # vừa quỹ đạo 3D không có hướng rõ ràng. Sụt lún đứng thuần túy (U)
                        # vẫn có directionality cao và được phát hiện chính xác.
                        if motion_significance < max(3.0, math.sqrt(len(step_lengths))) and directionality < 0.5:
                            current_level = "INFO"
                            logger.debug(
                                f"[GNSS-{station_id}] Jitter-suppressed: net3D={net_m*1000.0:.2f}mm, "
                                f"path3D={path_m*1000.0:.2f}mm, noise={noise_envelope_m*1000.0:.2f}mm, "
                                f"significance={motion_significance:.2f}, directionality={directionality:.2f}"
                            )

            # Dùng chung cho cả nhánh danger và safe (timeout/reset logic).
            import time as _time
            now = _time.time()
            
            # ✅ LOGIC ĐẾM XÁC NHẬN
            if current_level in ["WARNING", "CRITICAL"]:
                required_steps = critical_confirm_steps if current_level == "CRITICAL" else warning_confirm_steps
                latched_level = str(counter_info.get('latched_level') or '').upper()
                level_rank = {"INFO": 0, "WARNING": 1, "CRITICAL": 2}

                # Nếu đã latched ở mức nguy hiểm, giữ trạng thái pending cho tới khi thật sự về safe.
                # Tránh trường hợp CRITICAL vừa xuất hiện rồi tụt WARNING làm bridge auto-resolve sai.
                if latched_level in ("WARNING", "CRITICAL"):
                    counter_info['safe_count'] = 0
                    curr_rank = level_rank.get(current_level, 0)
                    latched_rank = level_rank.get(latched_level, 0)

                    # Còn cùng mức hoặc thấp hơn mức latched -> giữ pending, không resolve.
                    if curr_rank <= latched_rank:
                        return {'level': 'PENDING', 'category': 'gnss_velocity'}

                # Đã confirm level này và chưa về safe hoàn toàn -> không bắn lại.
                if counter_info['latched_level'] == current_level:
                    counter_info['safe_count'] = 0  # Reset safe countdown khi vẫn còn nguy hiểm
                    return {'level': 'PENDING', 'category': 'gnss_velocity'}

                # Nếu level thay đổi → Reset bộ đếm
                if counter_info['last_level'] != current_level:
                    counter_info['count'] = 1
                    counter_info['safe_count'] = 0
                    counter_info['last_level'] = current_level
                    counter_info['first_detected'] = now
                    logger.debug(f"[GNSS-{station_id}] Potential {current_level} detected, counting (1/{required_steps})")
                    return None
                else:
                    counter_info['count'] += 1

                    # Cap tại required_steps để không re-fire
                    if counter_info['count'] > required_steps:
                        counter_info['count'] = required_steps
                        return None

                    elapsed = now - counter_info['first_detected']
                    logger.debug(
                        f"[GNSS-{station_id}] {current_level} count: {counter_info['count']}/{required_steps}, "
                        f"elapsed: {elapsed:.1f}/{min_confirm_seconds}s"
                    )

                    # Phải đủ CẢ HAI: số lần VÀ thời gian tối thiểu
                    if counter_info['count'] == required_steps:
                        if elapsed < min_confirm_seconds:
                            logger.debug(
                                f"[GNSS-{station_id}] Count reached but too fast "
                                f"({elapsed:.2f}s < {min_confirm_seconds}s) — waiting"
                            )
                            # Không cap count — cho phép tiếp tục tăng để
                            # khi đủ thời gian sẽ re-check ở lần kế
                            counter_info['count'] = required_steps - 1
                            return None
                        counter_info['latched_level'] = current_level
                        counter_info['latched_time'] = now  # Ghi timestamp để tracking timeout
                        logger.warning(f"🚨 [GNSS-{station_id}] ✅ CONFIRMED {current_level} after {required_steps} readings over {elapsed:.1f}s!")
                        
                        message = f"🚨 CỰC KỲ NGUY HIỂM: {velocity_mms:.2f} mm/s ({velocity_class})" if current_level == "CRITICAL" else f"⚠️ Tốc độ nhanh: {velocity_mms:.4f} mm/s ({velocity_class})"
                        
                        audio_code = "gnss_warning"
                        if current_level == "CRITICAL":
                            audio_code = "gnss_critical"
                        
                        return {
                            "level": current_level,
                            "category": "gnss_velocity",
                            "message": message,
                            "audio_code": audio_code,
                            "details": {
                                "velocity_mm_s": velocity_mms,
                                "classification": velocity_class,
                                "confirmed_after": required_steps
                            }
                        }
                    else:
                        return None  # Chưa đủ số lần

            else:
                # ✅ AN TOÀN → cần đếm xác nhận an toàn trước khi resolve
                if counter_info['latched_level'] is not None:
                    # ⏱️ TIMEOUT CHECK: nếu alert latched > 15 phút mà vẫn safe → reset (xảy ra khi user dismiss)
                    latched_time = counter_info.get('latched_time', now)
                    elapsed_since_latched = now - latched_time
                    if elapsed_since_latched > 900:  # 900s = 15 phút
                        logger.warning(
                            f"🔄 [GNSS-{station_id}] Timeout auto-reset: alert latched {elapsed_since_latched:.0f}s ago, "
                            f"now safe → reset (user likely dismissed alert)"
                        )
                        counter_info['count'] = 0
                        counter_info['safe_count'] = 0
                        counter_info['last_level'] = None
                        counter_info['latched_level'] = None
                        return None
                    # Đang có alert đã xác nhận → đếm safe readings
                    counter_info['safe_count'] = counter_info.get('safe_count', 0) + 1
                    logger.debug(
                        f"[GNSS-{station_id}] Safe confirm: {counter_info['safe_count']}/{safe_confirm_steps} "
                        f"(was {counter_info['latched_level']})"
                    )
                    if counter_info['safe_count'] < safe_confirm_steps:
                        # Chưa đủ → giữ trạng thái PENDING, không cho bridge resolve
                        return {'level': 'PENDING'}
                    # Đủ safe_confirm_steps lần an toàn → reset hoàn toàn
                    logger.info(
                        f"✅ [GNSS-{station_id}] Confirmed safe after {counter_info['safe_count']} "
                        f"consecutive safe readings (was {counter_info['latched_level']})"
                    )
                    counter_info['count'] = 0
                    counter_info['safe_count'] = 0
                    counter_info['last_level'] = None
                    counter_info['latched_level'] = None
                else:
                    # Chưa có alert latched, chỉ đếm ngược count thường
                    if counter_info['count'] > 0:
                        counter_info['count'] = max(0, counter_info['count'] - 1)
                        logger.debug(f"[GNSS-{station_id}] Safe reading, counter → {counter_info['count']}/{max(warning_confirm_steps, critical_confirm_steps)}")
                    if counter_info['count'] == 0 and counter_info['last_level'] is not None:
                        logger.info(f"✅ [GNSS-{station_id}] Returned to safe after potential {counter_info['last_level']}")
                        counter_info['last_level'] = None
                        counter_info['latched_level'] = None

            return None

        except Exception as e:
            logger.exception(f"Error analyzing GNSS for station {station_id}: {e}")
            return None
