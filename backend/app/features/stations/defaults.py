"""Default station configuration values."""

from __future__ import annotations

def get_default_station_config():
    """
    ✅ Cấu hình mặc định cho mỗi trạm
    """
    return {
        "mqtt_topics": {
            "gnss": "",
            "rain": "",
            "water": "",
            "imu": ""
        },
        # Nhóm cảnh báo IMU
        "alerting": {
            "enabled": True
        },
        "ImuAlerting": {
            "tilt_warning_deg": 5.0,
            "tilt_critical_deg": 15.0,
            "imu_warning_confirm_steps": 2,
            "imu_critical_confirm_steps": 1,
            "imu_confirm_steps": 2,
            "shock_threshold_ms2": 5.0
        },
        # Nhóm cảnh báo GNSS (kỹ thuật)
        "GnssAlerting": {
            "gnss_max_hdop": 4.0,
            "gnss_warning_confirm_steps": 3,
            "gnss_critical_confirm_steps": 2,
            "gnss_confirm_steps": 3,
            "gnss_degraded_timeout": 300
        },
        "GnssIntegrity": {
            "process_max_hdop": 2.0,
            "process_min_sats": 10,
            "origin_max_gap_s": 2.0,
            "reference_event_alignment_s": 30.0,
            "reference_transition_samples": 6,
            "reacquire_max_spread_xy_m": 0.03,
            "reacquire_max_spread_u_m": 0.05
        },
        # Nhóm cảnh báo Mưa
        "RainAlerting": {
            "rain_intensity_watch_threshold": 10.0,
            "rain_intensity_warning_threshold": 25.0,
            "rain_intensity_critical_threshold": 50.0,
            "rain_warning_confirm_steps": 2,
            "rain_critical_confirm_steps": 1,
            "rain_confirm_steps": 2
        },
        # Nhóm cảnh báo Mực nước & Chuyển dịch
        "Water": {
            "warning_threshold": 0.15,
            "critical_threshold": 0.30,
            "water_warning_confirm_steps": 3,
            "water_critical_confirm_steps": 2,
            "water_confirm_steps": 3
        },
        "offline_thresholds": {
            "gnss": 30,
            "rain": 60,
            "water": 60,
            "imu": 2400
        },
        # Bảng Cruden & Varnes
        "GNSS_Classification": [
            { "name": "Extremely rapid", "mm_giay": 5000, "m_giay": 0.05, "desc": "> 5 m/s" },
            { "name": "Very rapid", "mm_giay": 4000.0, "m_giay": 0.04, "desc": "3 m/min to 5 m/s" },
            { "name": "Rapid", "mm_giay": 2000.0, "m_giay": 0.005, "desc": "1.8 m/h to 3 m/min" },
            { "name": "Moderate", "mm_giay": 1000.0, "m_giay": 0.03, "desc": "13 mm/mo to 1.8 m/h" },
            { "name": "Slow", "mm_giay": 0.000051, "m_giay": 0.01, "desc": "1.6 m/y to 13 mm/mo" },
            { "name": "Very slow", "mm_giay": 0.000001, "m_giay": 1.0E-09, "desc": "16 mm/y to 1.6 m/y" },
            { "name": "Extremely slow", "mm_giay": 0, "m_giay": 0.0, "desc": "< 16 mm/y" }
        ],
        "long_term_analysis": {
            "enabled": True,
            "window_days": 30,
            "trend_detection": True
        },
        # Cấu hình Truyền dữ liệu RTK (1Hz) ra ngoài
        "gnss_rtk_forwarding": {
            "enabled": False,
            "rtk_topic": "",       # Publish RTK Topic (1Hz, cm accuracy)
            "fields": {
                "X":   True,   # Tọa độ E hiện tại (m)
                "Y":   True,   # Tọa độ N hiện tại (m)
                "H":   True,   # Độ cao tuyệt đối (m)
                "dX":  True,   # Chuyển vị E (m)
                "dY":  True,   # Chuyển vị N (m)
                "dH":  True,   # Chuyển vị U (m)
                "VdX": True,   # Vận tốc E (mm/phút)
                "VdY": True,   # Vận tốc N (mm/phút)
                "VdH": True    # Vận tốc U (mm/phút)
            }
        },
        "gnss_aicaster_user": {
            "username": "",
            "caster_host": ""
        },
        "data_logging": {
            "enabled": True,
            "gnss": {
                "interval": 1,
                "enabled_fields": ["raw_gngga", "gga_utc", "gga_timestamp", "received_timestamp", "lat", "lon", "h", "pos_e", "pos_n", "pos_u", "total_displacement_mm", "candidate_step_displacement_mm", "displacement_change_threshold_mm", "position_change_significant", "vel_e", "vel_n", "vel_u", "speed_2d", "speed_2d_mm_s", "raw_vel_e_mm_s", "raw_vel_n_mm_s", "raw_vel_u_mm_s", "raw_speed_2d_mm_s", "velocity_method", "velocity_sample_count", "velocity_window_duration_s", "velocity_residual_rms_mm", "velocity_residual_mad_mm", "velocity_uncertainty_mm_s", "velocity_confidence_95_mm_s", "velocity_detection_threshold_mm_s", "velocity_z_score", "velocity_min_sigma", "velocity_reliable", "velocity_significant", "velocity_statistically_significant", "velocity_persistent", "velocity_confirmed", "velocity_confirmation_sample_count", "velocity_confirmation_duration_s", "velocity_confirmation_direction_cosine", "velocity_confirmation_accepted_sample", "velocity_confirmation_min_gap_s", "velocity_out_of_range", "fix_quality", "fix_mode", "num_sats", "hdop"],
                "save_rejected_raw": True,
                "save_forward_payload": True,
                "save_no_data_status": False
            },
            "imu": {
                "interval": 300,
                "enabled_fields": ["roll", "pitch", "yaw", "total_accel", "battery"]
            },
            "rain": {
                "interval": 300,
                "enabled_fields": ["intensity_mm_h", "accumulated_mm"]
            },
            "water": {
                "interval": 300,
                "enabled_fields": ["water_level", "intensity_mm_h"]
            }
        }
    }
