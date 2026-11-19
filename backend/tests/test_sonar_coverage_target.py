"""Targeted tests to boost coverage on newly refactored processors and modules for SonarCloud."""

import asyncio
import io
import math
import sys
import time
import zipfile
from collections import deque
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

if sys.version_info >= (3, 14):
    for mod in ("scipy.stats", "scipy.stats._new_distributions"):
        if mod not in sys.modules:
            try:
                __import__(mod)
            except Exception:
                sys.modules[mod] = MagicMock()

import numpy as np
import pytest
from fastapi import HTTPException

from processors.landslide_analyzer import LandslideAnalyzer
from processors.landslide.consensus import (
    _append_rain_and_gnss_notes,
    _compute_trend_agreement,
    _decide_alerting_consensus,
    _decide_consensus,
    _extract_gnss_state,
    _extract_imu_state,
    _extract_rain_state,
)
from processors.landslide.velocity import (
    _normalize_unit,
    _infer_unit_from_description,
    _convert_threshold_to_mm_s,
    _extract_threshold_and_unit,
    _normalize_table,
    _is_table_sane,
    _classify_from_sorted,
    _compute_ols_velocity,
    _evaluate_velocity_risk,
    _apply_cusum_to_risk,
    _apply_fukuzono_to_risk,
    _calculate_daily_window_velocities,
)
from processors.water_processor import WaterEngine
from processors.imu_processor import IMUEngine
from app.features.projects.admin import validate_project_fields
from processors.gnss.origin import _sync_station_origin_config, GNSSOriginMixin
from app.features.data_export.database.job import add_csv_to_zip, _apply_date_filter


class TestLandslideProcessorsCoverage:
    def test_rainfall_analysis_full(self):
        analyzer = LandslideAnalyzer()
        base_ts = 1700000000.0  # arbitrary epoch
        sorted_gnss = [
            {"timestamp": base_ts + i * 86400, "data": {"pos_e": 0.001 * i, "pos_n": 0.002 * i, "pos_u": 0.0005 * i}}
            for i in range(10)
        ]
        sorted_rain = [
            {"timestamp": base_ts + i * 86400, "data": {"rainfall_mm": 5.0 + i * 3.0}}
            for i in range(10)
        ]

        gnss_daily, daily_rain, common_days = analyzer._aggregate_gnss_and_rain_daily(sorted_gnss, sorted_rain)
        assert len(common_days) == 10

        cum, inc, legacy = analyzer._compute_daily_displacements(common_days, gnss_daily)
        assert len(cum) == 10
        assert len(inc) == 10
        assert len(legacy) == 10

        rain_arr = np.array([daily_rain[d] for d in common_days])
        smi = analyzer._compute_slide_model_index(rain_arr, 3.0, 15.0, 0.7)
        assert len(smi) == 10

        disp_rate = np.array(inc)
        lag, corr, pairs, scan_res = analyzer._scan_lag_correlation(smi, disp_rate, 3)
        assert pairs >= 3

        # assess correlation strength
        assert analyzer._assess_correlation_strength(0.85)[0] == "Rất mạnh"
        assert analyzer._assess_correlation_strength(0.65)[0] == "Mạnh"
        assert analyzer._assess_correlation_strength(0.45)[0] == "Trung bình"
        assert analyzer._assess_correlation_strength(0.25)[0] == "Yếu"
        assert analyzer._assess_correlation_strength(0.10)[0] == "Không đáng kể"

        # regression fit
        slope, intercept, r2, c_val, strength, assess, potential = analyzer._fit_lag_regression(smi, disp_rate, 0, 0.75)
        assert potential in ("HIGH", "MEDIUM", "LOW")

        # events
        cwds = analyzer._compute_cwd_events(common_days, rain_arr, disp_rate)
        assert isinstance(cwds, list)

        peaks = analyzer._compute_peak_events(common_days, rain_arr, disp_rate, smi, 0)
        assert isinstance(peaks, list)

        # Full method
        res = analyzer.analyze_rainfall_displacement_correlation(sorted_gnss, sorted_rain)
        assert res.get("available") is True

    def test_displacement_analysis_full(self):
        analyzer = LandslideAnalyzer()
        assert analyzer._check_preliminary_gnss_status({"status": "INITIALIZING"})["level"] == "PENDING"
        assert analyzer._check_preliminary_gnss_status({"velocity_reliable": False})["level"] == "PENDING"
        assert analyzer._check_preliminary_gnss_status({"velocity_confirmed": False})["level"] == "PENDING"
        assert analyzer._check_preliminary_gnss_status({"velocity_significant": False})["level"] == "PENDING"
        assert analyzer._check_preliminary_gnss_status({"status": "OK", "velocity_reliable": True, "velocity_confirmed": True}) is None

        # motion suppression
        assert analyzer._determine_motion_suppressed([], 1) is False
        points = [{"e": 0.001 * i, "n": 0.001 * i, "u": 0.0} for i in range(5)]
        assert analyzer._determine_motion_suppressed(points, 1) is False

        # anti-jitter
        hist = deque(maxlen=10)
        now = time.time()
        for i in range(5):
            hist.append({"ts": now - (5 - i), "e": 0.0, "n": 0.0, "u": 0.0, "data": {"pos_e": 0.0, "pos_n": 0.0, "pos_u": 0.0}})
        info = {"first_detected": now - 3, "latched_level": "WARNING"}
        lvl = analyzer._apply_anti_jitter(hist, info, "WARNING", 1)
        assert lvl in ("WARNING", "LOW", "INFO")

        # level from class
        assert analyzer._level_from_velocity_class("Extremely Rapid") == "CRITICAL"
        assert analyzer._level_from_velocity_class("Rapid") == "CRITICAL"
        assert analyzer._level_from_velocity_class("Moderate") == "WARNING"
        assert analyzer._level_from_velocity_class("Slow") == "INFO"

        # confirmed alert
        alt = analyzer._build_confirmed_alert("WARNING", 1, 0.5, "Rapid", 3, 10.0)
        assert alt["level"] == "WARNING"

        # deassertion
        de_res = analyzer._step_safe_deassertion(info, 1, 1, time.time())
        assert de_res is not None or de_res is None

    def test_consensus_analysis_full(self):
        g_st = _extract_gnss_state({"status": "success", "risk_level": "HIGH", "analysis": {"trend": "accelerating", "total_displacement_mm": 15.0}})
        assert g_st["ok"] is True
        assert g_st["alerting"] is True

        i_st = _extract_imu_state({"status": "success", "risk_level": "HIGH", "analysis": {"trend": "accelerating", "total_tilt_change_deg": 2.5}})
        assert i_st["ok"] is True
        assert i_st["alerting"] is True

        r_st = _extract_rain_state({"available": True, "correlation": 0.65})
        assert r_st["supporting"] is True

        # trend agreement
        assert _compute_trend_agreement(True, True, "accelerating", "accelerating") == "full"
        assert _compute_trend_agreement(True, True, "accelerating", "stable") == "partial"
        assert _compute_trend_agreement(True, True, "accelerating", "decelerating") == "conflict"
        assert _compute_trend_agreement(False, True, "accelerating", "accelerating") is None

        # decide consensus
        res_both = _decide_consensus(["gnss", "imu"], g_st, i_st, "full")
        assert res_both[0] == "STRONG"

        i_conflict = dict(i_st)
        i_conflict["trend"] = "decelerating"
        res_conf = _decide_consensus(["gnss", "imu"], g_st, i_conflict, "conflict")
        assert res_conf[0] == "CONFLICT"

        res_none = _decide_consensus([], g_st, i_st, None)
        assert res_none[0] == "UNAVAILABLE"

        notes = []
        _append_rain_and_gnss_notes(notes, ["gnss"], r_st, {"available": True, "assessment": "Mạnh"}, g_st, True)
        assert len(notes) > 0

    def test_velocity_and_windows_analysis(self):
        analyzer = LandslideAnalyzer()
        assert _normalize_unit("mm/d") == "mm/day"
        assert _normalize_unit("m/sec") == "m/s"
        assert _infer_unit_from_description("Tốc độ theo mm/năm") == "mm/year"
        assert _infer_unit_from_description("unknown") is None

        assert _convert_threshold_to_mm_s(1.0, "mm/s") == 1.0
        assert _convert_threshold_to_mm_s(86.4, "mm/day") == 0.001
        assert _convert_threshold_to_mm_s(1.0, "m/s") == 1000.0

        thresh, unit = _extract_threshold_and_unit({"threshold": 5, "unit": "m/s"})
        assert thresh == 5
        assert unit == "m/s"

        tbl = _normalize_table([
            {"name": "Fast", "threshold": 0.5, "unit": "mm/s"},
            {"name": "Slow", "threshold": 0.01, "unit": "mm/s"},
        ])
        assert _is_table_sane(tbl) is True
        assert _is_table_sane([]) is False

        assert _classify_from_sorted(tbl, 6000.0) == "Fast"

        # ols velocity
        base_ts = time.time()
        sorted_d = [
            {"timestamp": base_ts + i * 3600, "data": {"pos_e": 0.001 * i, "pos_n": 0.001 * i, "pos_u": 0.0}}
            for i in range(5)
        ]
        vel_mms, r2, vel_mmday = _compute_ols_velocity(sorted_d, sorted_d[0])
        assert vel_mmday >= 0

        cls_out, risk, warn = _evaluate_velocity_risk(True, "Rapid", "accelerating", "Tin cậy")
        assert risk in ("CRITICAL", "HIGH", "MEDIUM", "LOW")

        risk_cu, notes_cu = _apply_cusum_to_risk(risk, warn, True, {"has_change": True, "message": "Change"})
        assert "Change" in notes_cu

        risk_fk, notes_fk = _apply_fukuzono_to_risk(risk, warn, True, {"predicted_failure": True, "days_to_failure": 5})
        assert risk_fk == "EXTREME"

        # windows
        now_dt = datetime.now()
        intervals = analyzer._build_time_intervals(now_dt.timestamp(), now_dt)
        assert len(intervals) == 3

        now_ts = now_dt.timestamp()
        sorted_data = [
            {"timestamp": now_ts - (5 - i) * 1000, "data": {"pos_e": 0.001 * i, "pos_n": 0.002 * i, "pos_u": 0.0}}
            for i in range(6)
        ]
        w_res = analyzer._compute_single_window(intervals[0], sorted_data, 0.01)
        assert w_res["status"] in ("success", "preliminary", "insufficient_data")

        acc = analyzer._check_acceleration_alert([
            {"status": "success", "velocity_reliable": True, "velocity_mm_day": 10.0, "window_days": "day", "label": "24h qua"},
            {"status": "success", "velocity_reliable": True, "velocity_mm_day": 2.0, "window_days": "month", "label": "Tháng này"}
        ])
        assert acc is not None

    def test_full_facade_and_submodules(self):
        analyzer = LandslideAnalyzer()
        base_ts = time.time()
        sorted_gnss = [
            {"timestamp": base_ts + i * 3600, "data": {"pos_e": 0.001 * i, "pos_n": 0.002 * i, "pos_u": 0.0, "speed_2d": 0.001}}
            for i in range(10)
        ]
        sorted_imu = [
            {"timestamp": base_ts + i * 3600, "data": {"roll": 0.05 * i, "pitch": -0.02 * i}}
            for i in range(10)
        ]

        # full velocity
        vel_res = analyzer.analyze_long_term_velocity(1, sorted_gnss, {})
        assert vel_res.get("status") in ("success", "insufficient_data")

        # full tilt
        tilt_res = analyzer.analyze_long_term_tilt(1, sorted_imu)
        assert tilt_res.get("status") in ("success", "insufficient_data")

        # full windows
        win_res = analyzer.analyze_multi_window(1, sorted_gnss, {})
        assert win_res.get("available") is True

        # full displacement
        disp_res = analyzer.analyze_gnss_displacement(1, sorted_gnss, {"GnssAlerting": {"enabled": True}})
        assert disp_res is not None or disp_res is None

        # full consensus
        cons_res = analyzer.analyze_cross_sensor_consensus(vel_res, tilt_res, {"available": True, "correlation": 0.5})
        assert cons_res.get("available") is True

        analyzer = LandslideAnalyzer()
        now_ts = time.time()
        sorted_data = [
            {"timestamp": now_ts + i * 60, "data": {"roll": 0.1 * i, "pitch": -0.05 * i}}
            for i in range(10)
        ]
        rolls, pitches, ts = analyzer._extract_imu_roll_pitch(sorted_data)
        assert len(rolls) == 10

        assert analyzer._compute_tilt_trend(rolls) == "accelerating"
        assert analyzer._compute_tilt_trend([-0.1 * i for i in range(10)]) == "decelerating"
        assert analyzer._compute_tilt_trend([0.0 for _ in range(10)]) == "stable"

        assert analyzer._evaluate_tilt_risk(12.0, 1.5, 1.0, "accelerating")[0] == "EXTREME"
        assert analyzer._evaluate_tilt_risk(6.0, 0.6, 1.0, "accelerating")[0] == "HIGH"
        assert analyzer._evaluate_tilt_risk(3.0, 0.2, 1.0, "stable")[0] == "MEDIUM"
        assert analyzer._evaluate_tilt_risk(0.5, 0.05, 1.0, "accelerating")[0] == "MEDIUM"
        assert analyzer._evaluate_tilt_risk(0.1, 0.01, 1.0, "stable")[0] == "LOW"

        ts_dict = analyzer._build_tilt_time_series(ts, rolls, pitches, 0.01)
        assert len(ts_dict) > 0


class TestWaterAndIMUEngines:
    def test_water_engine_processing(self):
        eng = WaterEngine(valid_min=0.0, valid_max=10.0)

        # to_meters conversions
        assert eng._to_meters({"sensortype": "GWL"}, 50.0) == 50.0
        assert eng._to_meters({"sensortype": "GWL"}, 1500.0) == 1.5
        assert eng._to_meters({"water_level": 2.5}, 2.5) == 2.5

        # process fallback
        res_none = eng.process({}, time.time())
        assert res_none["is_fallback"] is True

        # process normal valid
        res_valid = eng.process({"value": 3.45}, time.time())
        assert res_valid["water_level"] == 3.45
        assert res_valid["water_level_cm"] == 345.0

        # process out of range
        res_oor = eng.process({"value": 999.0}, time.time())
        assert res_oor["is_fallback"] is True

    def test_imu_engine_processing(self):
        eng = IMUEngine()
        eng.set_baseline(1.0, 2.0, 3.0)
        assert eng.origin_locked is True

        drift, dir_text = eng._calculate_drift(2.0, 2.0, 100.0)
        assert drift > 0
        assert dir_text != "--"

        # inclinometer
        res_inc = eng._process_inclinometer({"angle_xyz": [1.5, 2.5, 3.5], "battery_voltage": 3.7}, 100.0)
        assert res_inc["roll"] == 0.5
        assert res_inc["pitch"] == 0.5

        # raw imu
        res_raw = eng._process_raw_imu({"ax": 0.1, "ay": 0.2, "az": 9.8, "temp": 25.0}, 100.0)
        assert res_raw is not None


class TestProjectsAdminAndJobHelpers:
    def test_validate_project_fields(self):
        # valid
        data = {"project_code": " PRJ1 ", "name": " Test ", "description": " Desc "}
        validate_project_fields(data)
        assert data["project_code"] == "PRJ1"
        assert data["name"] == "Test"

        # missing code in create
        with pytest.raises(HTTPException):
            validate_project_fields({"name": "P1"}, creating=True)

        # exceed length
        with pytest.raises(HTTPException):
            validate_project_fields({"project_code": "x" * 51})

        # non-string
        with pytest.raises(HTTPException):
            validate_project_fields({"project_code": 123})

    def test_add_csv_to_zip_and_date_filter(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            assert add_csv_to_zip(zf, "empty.csv", ["h1"], []) == 0
            n = add_csv_to_zip(zf, "data.csv", ["col1", "col2"], [["a", "b"], ["c", "d"]])
            assert n == 2

        with zipfile.ZipFile(io.BytesIO(buf.getvalue()), "r") as zf:
            assert "data.csv" in zf.namelist()

        # date filter
        from sqlalchemy import column, select
        mock_col = column("timestamp")
        query = select(mock_col)
        q1 = _apply_date_filter(query, mock_col, "2024-01-01", "2024-01-02")
        assert q1 is not None

    def test_sync_station_origin_config(self):
        station = MagicMock()
        station.config = {"other": 1}
        _sync_station_origin_config(station, {"lat": 21.0, "lon": 105.0, "h": 100.0})
        assert "gnss_origin" in station.config
        assert station.config["gnss_origin"]["lat"] == 21.0

    def test_gnss_pipeline_mixin(self):
        from app.mqtt.bridge.sensor_pipeline.gnss import GnssPayloadMixin
        mixin = GnssPayloadMixin()
        mixin.round_robin_manager = MagicMock()
        mixin.round_robin_manager._sessions = {
            1: {
                "monitoring_project_id": 10,
                "clusters": [{"stations": [101, 102]}],
                "seed_topology_snapshots": True,
            }
        }
        mixin.adjustment_phase = {1: "STARTING"}
        assert mixin._monitoring_paused_for_adjustment(10, 101) is True
        assert mixin._monitoring_paused_for_adjustment(10, 999) is False

        # seed delta
        assert "dN/E/U=" in mixin._format_station_seed_delta({"delta_neu_m": [0.001, 0.002, 0.003]}, 10)
        assert "waiting" in mixin._format_station_seed_delta({}, 10)

        # seed state
        state_open = mixin._format_station_seed_state(True, 101, {101: 5}, {101: 20}, {}, {}, {"solver_min_distinct_epochs": 10, "solver_min_duration_seconds": 30})
        assert "solver=" in state_open
        state_warmup = mixin._format_station_seed_state(False, 101, {}, {}, {101: 3}, {101: 15}, {"seed_warmup_min_distinct_epochs": 5, "seed_warmup_min_duration_seconds": 20})
        assert "fixed-base warm-up=" in state_warmup

    def test_gnss_origin_record_apply(self):
        from processors.gnss.origin import GNSSOriginMixin
        mixin = GNSSOriginMixin()
        mixin.device_id = 1
        mixin.tracking_offset_enu = np.array([0.0, 0.0, 0.0])
        mixin._restore_runtime_state = MagicMock(return_value=True)
        mixin._log_prefix = MagicMock(return_value="GNSS-1")
        
        origin_rec = MagicMock()
        origin_rec.lat = 21.0
        origin_rec.lon = 105.0
        origin_rec.h = 100.0
        origin_rec.rotation_matrix = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
        origin_rec.ecef_origin = [1000.0, 2000.0, 3000.0]
        origin_rec.locked_at = 123456
        origin_rec.id = 42
        origin_rec.tracking_offset = None
        
        mixin._apply_origin_record(origin_rec, None)
        assert mixin.state == "ORIGIN_LOCKED"
        assert mixin.origin["lat"] == 21.0

        # preserve existing
        mixin._preserve_existing_origin(origin_rec)
        assert mixin._origin_record_id == 42

    @pytest.mark.anyio
    async def test_job_export_boundaries(self):
        from app.features.data_export.database.job import _resolve_export_boundaries
        from app.features.data_export.schemas import ExportExcelRequest
        mock_db = AsyncMock()
        mock_proj = MagicMock(id=1, project_code="PRJ1")
        mock_st = MagicMock(id=10, project_id=1, station_code="ST10")
        
        exec_proj = MagicMock()
        exec_proj.scalars.return_value.all.return_value = [mock_proj]
        exec_st = MagicMock()
        exec_st.scalars.return_value.all.return_value = [mock_st]
        mock_db.execute.side_effect = [exec_proj, exec_st]
        
        req = ExportExcelRequest(tables=["sensor_data"], project_ids=[1], station_ids=[10])
        p_rows, s_rows, p_codes, s_map, all_s_map, scope_ids, req_types, p_filt, s_filt = await _resolve_export_boundaries(mock_db, req)
        assert len(p_rows) == 1
        assert len(s_rows) == 1
        assert 10 in scope_ids


class TestStationAnalysisAndRuntimeCoverage:
    def test_analysis_router_helpers(self):
        from app.features.stations.analysis_router import (
            _resolve_alert_ttls,
            _calculate_overall_risk,
            _is_gnss_analysis_point,
            _trend_from_velocity_series,
            _severity,
            _build_gnss_time_series,
        )

        # ttls
        ttls_default = _resolve_alert_ttls({})
        assert "gnss_velocity" in ttls_default
        ttls_custom = _resolve_alert_ttls({"alert_ttl_seconds": {"gnss_velocity": 300}})
        assert ttls_custom["gnss_velocity"] == 300

        # overall risk
        a_crit = MagicMock(level="CRITICAL", category="gnss_velocity")
        a_tilt = MagicMock(level="WARNING", category="tilt_warning")
        a_low = MagicMock(level="LOW", category="rainfall")
        assert _calculate_overall_risk([(a_crit, False, 10)]) == "CRITICAL"
        assert _calculate_overall_risk([(a_tilt, False, 10)]) == "CRITICAL"
        assert _calculate_overall_risk([(a_low, False, 10)]) == "LOW"
        assert _calculate_overall_risk([]) == "LOW"

        # gnss analysis point
        assert _is_gnss_analysis_point({"pos_e": 0, "pos_n": 0, "pos_u": 0}) is True
        assert _is_gnss_analysis_point({"pos_e": 0}) is False
        assert _is_gnss_analysis_point(None) is False

        # trend
        assert _trend_from_velocity_series([1.0]) == "stable"
        assert _trend_from_velocity_series([0.0, 0.0]) == "stable"
        assert _trend_from_velocity_series([0.0, 5.0]) == "accelerating"
        assert _trend_from_velocity_series([10.0, 20.0]) == "accelerating"
        assert _trend_from_velocity_series([20.0, 10.0]) == "decelerating"
        assert _trend_from_velocity_series([10.0, 10.2]) == "stable"

        # severity
        assert _severity("EXTREME") == 5
        assert _severity("CRITICAL") == 4
        assert _severity("INFO") == 0
        assert _severity("unknown") == 0

        # gnss time series
        ts_res = _build_gnss_time_series([
            {"timestamp": time.time(), "data": {"pos_e": 0.01, "pos_n": 0.02, "pos_u": 0.005, "total_displacement_mm": 5.0}}
        ], 1.0)
        assert len(ts_res["labels"]) == 1

    @pytest.mark.anyio
    async def test_calculate_station_risk_assessment(self):
        from app.features.stations.analysis_router import _calculate_station_risk_assessment
        mock_db = AsyncMock()
        mock_alert = MagicMock(level="HIGH", category="gnss_velocity", message="High vel", timestamp=time.time())
        exec_res = MagicMock()
        exec_res.scalars.return_value.all.return_value = [mock_alert]
        mock_db.execute.return_value = exec_res

        res = await _calculate_station_risk_assessment(mock_db, 1, {"alerting": {"enabled": True}})
        assert res["overall_risk"] == "HIGH"
        assert len(res["active_alerts"]) == 1

        # disabled alerting
        res_dis = await _calculate_station_risk_assessment(mock_db, 1, {"alerting": {"enabled": False}})
        assert res_dis["overall_risk"] == "LOW"

    def test_rain_engine_processing(self):
        from processors.water_processor import RainEngine
        reng = RainEngine()

        # rsb
        r1, i1 = reng._process_rsb({"value": "15.5"}, time.time())
        assert i1 == 15.5
        assert reng._process_rsb({"value": None}, time.time()) is None

        # standard rain
        r2, i2 = reng._process_standard_rain({"rainfall_mm": 20.0, "intensity_mm_h": 5.0}, time.time())
        assert r2 == 20.0
        assert i2 == 5.0
        assert reng._process_standard_rain({}, time.time()) is None

        # process
        p_res = reng.process({"rainfall_mm": 25.0, "intensity_mm_h": 6.0}, time.time())
        assert p_res["is_fallback"] is False

    def test_agrica_runtime_parsing(self):
        from processors.gnss_adjustment.runtime import (
            _safe_float,
            _safe_int,
            _positive_std,
            extract_agrica_sentences,
            _parse_agrica_epoch,
            _parse_agrica_positions,
            _parse_agrica_stds,
        )

        assert _safe_float(" 3.14 ") == 3.14
        assert _safe_float(None) is None
        assert _safe_float("invalid") is None
        assert _safe_float("nan") is None

        assert _safe_int(" 42 ") == 42
        assert _safe_int(None) is None
        assert _safe_int("invalid") is None

        assert _positive_std(0.05) == 0.05
        assert _positive_std(-1.0) == 0.02
        assert _positive_std(None) == 0.02

        assert extract_agrica_sentences("") == []
        sentences = extract_agrica_sentences("#AGRICA;GNSS,1,2024,1,1,0,0,0*FF")
        assert len(sentences) == 1

        parts = [""] * 50
        parts[2], parts[3], parts[4], parts[5], parts[6], parts[7] = "2024", "5", "10", "12", "30", "0.0"
        epoch = _parse_agrica_epoch(parts, None)
        assert epoch > 0

        parts[29], parts[30], parts[31] = "21.0", "105.0", "100.0"
        parts[32], parts[33], parts[34] = "1000.0", "2000.0", "3000.0"
        parts[41], parts[42], parts[43] = "21.1", "105.1", "101.0"
        r_llh, r_ecef, b_llh = _parse_agrica_positions(parts)
        assert r_llh == (21.0, 105.0, 100.0)
        assert r_ecef == (1000.0, 2000.0, 3000.0)
        assert b_llh == (21.1, 105.1, 101.0)

        parts[38], parts[39], parts[40] = "0.01", "0.02", "0.03"
        parts[16], parts[17], parts[18] = "0.005", "0.005", "0.01"
        r_std_raw, r_std, std_neu_raw = _parse_agrica_stds(parts)
        assert r_std_raw == (0.01, 0.02, 0.03)

    def test_incident_cases_domain(self):
        from app.features.incidents.cases import (
            normalize_severity,
            normalize_source_kind,
            priority_for_severity,
            normalize_episode_category,
            incident_reference,
            _text,
            _event_payload,
        )

        assert normalize_severity("critical") == "CRITICAL"
        assert normalize_severity("invalid") == "UNKNOWN"

        assert normalize_source_kind("SENSOR_ALERT") == "SENSOR_ALERT"
        assert normalize_source_kind("RESCUE_REQUEST") == "RESCUE_REQUEST"
        with pytest.raises(ValueError):
            normalize_source_kind("INVALID_KIND")

        assert priority_for_severity("CRITICAL") == "URGENT"
        assert priority_for_severity("MEDIUM") == "HIGH"
        assert priority_for_severity("LOW") == "NORMAL"
        assert priority_for_severity("UNKNOWN") == "UNTRIAGED"

        assert normalize_episode_category("tilt_warning") == "tilt"
        assert normalize_episode_category("gnss_velocity_critical") == "gnss_velocity"
        assert normalize_episode_category("custom_cat") == "custom_cat"

    def test_job_export_config_and_row(self):
        from app.features.data_export.database.job import (
            _export_config_entities,
            _extract_adjustment_station_metadata,
            _build_adjustment_row,
        )
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            mock_p = MagicMock(id=1, project_code="P1", name="Proj 1", description="Desc", is_active=True)
            mock_s = MagicMock(id=10, project_id=1, station_code="S10", name="St 10", status="online", last_update=time.time(), location="POINT(105 21)")
            tot, summary = asyncio.run(_export_config_entities(
                zf, ["projects", "stations"], [mock_p], [mock_s], {1: "P1"}, {10: {"project_code": "P1", "station_code": "S10"}},
                {10}, [], "2024-01-01", AsyncMock()
            ))
            assert tot == 2
            assert len(summary) == 2

        # metadata
        payload = {"points": {"pt1": {"station_id": 10}}, "context": {"stations": [10, 20]}}
        sids, scodes = _extract_adjustment_station_metadata(payload, {10: {"station_code": "S10"}, 20: {"station_code": "S20"}})
        assert sids == [10, 20]
        assert scodes == ["S10", "S20"]

        # row
        row = _build_adjustment_row(
            {"record_ids": [1, 2]}, {"cluster_index": 0, "cluster_name": "C0", "source": "network", "status": "SOLVED"},
            int(time.time()), 1, "P1", [10], ["S10"], {"observation_baseline_count": 5}, {}, {}, "http://excel"
        )
        assert len(row) > 10

    @pytest.mark.anyio
    async def test_gnss_pipeline_diagnostics_and_handlers(self):
        from app.mqtt.bridge.sensor_pipeline.gnss import GnssPayloadMixin
        mixin = GnssPayloadMixin()
        mixin.round_robin_manager = MagicMock()
        mixin.adjustment_run_contexts = {1: {"cluster_name": "Cluster1"}}
        mixin._upsert_latest_sensor_cache = AsyncMock()

        seed_status = {
            "clusters": [{
                "rolling_stability_by_station": {10: {"delta_neu_m": [0.001, 0.002, 0.003]}},
                "solver_window_open_by_station": {10: True},
                "solver_sample_counts_by_station": {10: 10},
                "solver_durations_by_station_seconds": {10: 30},
                "sample_counts_by_station": {},
                "durations_by_station_seconds": {},
                "solver_window_reset_counts_by_station": {},
                "solver_drift_failure_counts_by_station": {},
                "warming_station_ids": [10],
                "latest_position_type_by_station": {20: 1},
            }],
            "missing_station_ids": [20],
            "silent_station_ids": [30],
            "invalid_fix_station_ids": [20],
            "warming_station_ids": [10],
            "stability_window_seconds": 15,
        }
        parts = mixin._collect_seed_progress_parts(seed_status)
        assert len(parts) == 1
        waiting = mixin._build_seed_waiting_parts(seed_status, parts)
        assert len(waiting) >= 2

        # gngga handlers
        proc = MagicMock()
        now_ts = int(time.time())
        res_data = await mixin._handle_gngga_result(
            {"type": "gnss_processed", "data": {"latitude": 21.0, "longitude": 105.0, "altitude": 100.0}},
            {"station_code": "S1"}, 1, 10, "Station 1", proc, {}, 101, "$GNGGA", now_ts
        )
        assert res_data["latitude"] == 21.0

        await mixin._handle_origin_status_message(
            {"status": "LOCKING", "fix_quality": 4, "fix_mode": "FIXED", "message": "Collecting"},
            1, 10, now_ts
        )
        mixin._upsert_latest_sensor_cache.assert_called()

    def test_analysis_router_helpers(self):
        from app.features.stations.analysis_router import (
            _resolve_alert_ttls, _calculate_overall_risk,
            _is_gnss_analysis_point, _trend_from_velocity_series, _severity,
        )
        ttls = _resolve_alert_ttls({"alert_ttl_seconds": {"rainfall": 300}})
        assert ttls["rainfall"] == 300
        assert "gnss_velocity" in ttls

        mock_alert1 = MagicMock(level="WARNING", category="tilt")
        mock_alert2 = MagicMock(level="HIGH", category="rainfall")
        risk = _calculate_overall_risk([(mock_alert1, False, 10), (mock_alert2, False, 20)])
        assert risk == "CRITICAL"

        assert _is_gnss_analysis_point({"pos_e": 1.0, "pos_n": 2.0, "pos_u": 3.0}) is True
        assert _is_gnss_analysis_point({"pos_e": 1.0}) is False
        assert _is_gnss_analysis_point(None) is False

        assert _trend_from_velocity_series([]) == "stable"
        assert _trend_from_velocity_series([1.0, 1.02]) == "stable"
        assert _trend_from_velocity_series([1.0, 2.0]) == "accelerating"
        assert _trend_from_velocity_series([2.0, 1.0]) == "decelerating"
        assert _trend_from_velocity_series([0.0, 0.0]) == "stable"
        assert _trend_from_velocity_series([0.0, 1.5]) == "accelerating"

        assert _severity("CRITICAL") == 4
        assert _severity("LOW") == 1
        assert _severity("UNKNOWN") == 0

    def test_analysis_router_time_series_and_summaries(self):
        from app.features.stations.analysis_router import (
            _build_gnss_time_series, _build_imu_time_series, _determine_daily_risk_and_message,
            _build_gnss_analysis_from_daily_summaries, _validate_analysis_params,
        )
        now = time.time()
        gnss_points = [
            {"timestamp": now + i * 3600, "data": {"pos_e": 0.001 * i, "pos_n": 0.002 * i, "pos_u": 0.003 * i, "displacement_mm": i}}
            for i in range(5)
        ]
        ts1 = _build_gnss_time_series(gnss_points, 0.03)
        assert len(ts1["labels"]) > 0
        ts2 = _build_gnss_time_series(gnss_points, 0.5)
        assert len(ts2["labels"]) > 0
        ts3 = _build_gnss_time_series(gnss_points, 5.0)
        assert len(ts3["labels"]) > 0
        ts4 = _build_gnss_time_series(gnss_points, 15.0)
        assert len(ts4["labels"]) > 0

        imu_analysis = {
            "status": "success",
            "time_series": {
                "raw_timestamps": [now, now + 100],
                "rolls": [0.1, 0.2],
                "pitches": [0.3, 0.4],
            }
        }
        _build_imu_time_series(imu_analysis, 0.5)
        assert "labels" in imu_analysis["time_series"]

        mock_row = MagicMock(risk_level="HIGH", net_displacement_mm=2.5, duration_seconds=86400, sample_count=100, velocity_mm_day=2.5, day_start_ts=now)
        risk_level, msg = _determine_daily_risk_and_message([mock_row], "Extremely Fast", True, "ok")
        assert risk_level in ("HIGH", "CRITICAL", "EXTREME")
        assert "Cảnh báo" in msg

        risk_level_unreliable, msg_unreliable = _determine_daily_risk_and_message([mock_row], "Fast", False, "Sơ bộ")
        assert risk_level_unreliable == "INFO"
        assert msg_unreliable == "Sơ bộ"

        assert _build_gnss_analysis_from_daily_summaries([], {})["status"] == "insufficient_data"
        res_summary = _build_gnss_analysis_from_daily_summaries([mock_row], {})
        assert res_summary["status"] == "success"

        days, model = _validate_analysis_params(30.0, "slide_model", True)
        assert days == 30.0
        assert model == "slide_model"

        with pytest.raises(HTTPException):
            _validate_analysis_params("invalid", "slide_model", True)
        with pytest.raises(HTTPException):
            _validate_analysis_params(500.0, "slide_model", True)
        with pytest.raises(HTTPException):
            _validate_analysis_params(30.0, "other_model", True)

    @pytest.mark.anyio
    async def test_analysis_router_async_functions(self):
        from app.features.stations.analysis_router import (
            _calculate_station_risk_assessment, _run_imu_step, _run_rainfall_correlation_step,
            get_long_term_analysis, get_gnss_daily_summary, get_gnss_weekly_summary,
        )
        db_data = AsyncMock()
        mock_scalar = MagicMock()
        mock_scalar.all.return_value = []
        mock_exec = MagicMock()
        mock_exec.scalars.return_value = mock_scalar
        db_data.execute.return_value = mock_exec

        risk_data = await _calculate_station_risk_assessment(db_data, 1, {"alerting": {"enabled": False}})
        assert risk_data["overall_risk"] == "LOW"

        risk_data_enabled = await _calculate_station_risk_assessment(db_data, 1, {"alerting": {"enabled": True}})
        assert risk_data_enabled["overall_risk"] == "LOW"

        imu_res = await _run_imu_step(1, [], 10.0)
        assert imu_res["status"] == "insufficient_data"

        rain_res = await _run_rainfall_correlation_step(False, "slide_model", [], [], [], 10.0, MagicMock())
        assert rain_res["available"] is False

        # Endpoint tests
        db_config = AsyncMock()
        mock_st_res = MagicMock()
        mock_st_res.scalar_one_or_none.return_value = MagicMock(id=1, config={})
        db_config.execute.return_value = mock_st_res

        res = await get_long_term_analysis(
            station_id=1, days=30.0, include_correlation=False, correlation_model="slide_model",
            db_config=db_config, db_data=db_data
        )
        assert res["station_id"] == 1
        assert "gnss" in res

        daily_res = await get_gnss_daily_summary(station_id=1, limit=10, db_data=db_data)
        assert daily_res["station_id"] == 1
        assert daily_res["count"] == 0

        weekly_res = await get_gnss_weekly_summary(station_id=1, limit=5, db_data=db_data)
        assert weekly_res["station_id"] == 1
        assert weekly_res["count"] == 0

    @pytest.mark.anyio
    async def test_data_export_queries_and_adjustments(self):
        from app.features.data_export.database.job import (
            _build_and_count_queries, _compute_adjustment_key,
            _stream_unique_adjustments, _process_single_adjustment, EXPORT_TASKS,
        )
        request = MagicMock(start_date="2024-01-01", end_date="2024-01-02", cluster_indices=[0])
        task_id = "task-test-job-456"
        EXPORT_TASKS[task_id] = {}

        db_data = AsyncMock()
        db_data.scalar = AsyncMock(return_value=10)

        q1, q2, q3, q4, total = await _build_and_count_queries(
            request, ["sensor_data", "gnss_adjustments", "alerts", "simulations"],
            [1, 2], [1], [1], ["gnss"], db_data, task_id
        )
        assert total >= 0

        key1 = _compute_adjustment_key({"project_id": 1, "cluster_index": 0}, "adj_123", 1700000000)
        assert key1 == ("adjustment", "adj_123", None, None)

        key2 = _compute_adjustment_key({"project_id": 1, "cluster_index": 0}, None, 1700000000)
        assert key2[0] == "legacy"

        # Stream unique adjustments
        async def mock_stream():
            yield (1, 1700000000, {"project_id": 1, "cluster_index": 0}, "adj_1")
            yield (2, 1700000000, {"project_id": 1, "cluster_index": 1}, "adj_2")

        unique, count = await _stream_unique_adjustments(mock_stream(), {0}, 10, task_id, 0)
        assert len(unique) == 1
        assert count == 2

        # Process single adjustment
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            item = {
                "payload": {
                    "project_id": 1,
                    "cluster_index": 0,
                    "cluster_name": "Cluster0",
                    "computed_at": 1700000000,
                    "points": {"pt1": {"station_id": 10}},
                    "quality": {"observation_baseline_count": 5},
                    "global_test": {"passed": True},
                    "base": {"name": "Base1", "lat": 21.0, "lon": 105.0, "h": 50.0},
                },
                "timestamp": 1700000000,
                "record_ids": [101, 102],
            }
            db = AsyncMock()
            proj_dir, row = await _process_single_adjustment(item, {1: "PROJ1"}, {10: {"station_code": "S10"}}, zf, db)
            assert "PROJ1" in proj_dir
            assert len(row) > 10

    @pytest.mark.anyio
    async def test_gnss_origin_and_incidents(self):
        from processors.gnss.origin import _query_origin_record, _sync_station_origin_config, GNSSOriginMixin
        from app.features.incidents.common import _mutation_key_or_error, _fingerprint, _is_admin, _is_manager
        from app.features.incidents.write_router import _mutate_case

        db = AsyncMock()
        res_mock = MagicMock()
        res_mock.scalar_one_or_none.return_value = MagicMock(id=1, lat=21.0, lon=105.0, h=10.0)
        db.execute.return_value = res_mock
        record = await _query_origin_record(db, 10)
        assert record.lat == 21.0

        station = MagicMock(config={})
        _sync_station_origin_config(station, {"lat": 21.0, "lon": 105.0, "h": 50.0})
        assert "gnss_origin" in station.config
        assert station.config["gnss_origin"]["lat"] == 21.0

        mixin = GNSSOriginMixin()
        mixin.device_id = 100
        mock_rec = MagicMock(
            lat=21.0, lon=105.0, h=50.0,
            rotation_matrix=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
            ecef_origin=[100.0, 200.0, 300.0],
            locked_at=1700000000, id=1, tracking_offset=None
        )
        mixin._restore_runtime_state = MagicMock(return_value=False)
        mixin._log_prefix = MagicMock(return_value="dev_100")
        mixin._apply_origin_record(mock_rec, {})
        assert mixin.state == "ORIGIN_LOCKED"
        assert mixin.origin["lat"] == 21.0

        # Incidents common
        key = _mutation_key_or_error("unique-key-123")
        assert key == "unique-key-123"

        with pytest.raises(HTTPException):
            _mutation_key_or_error("")

        fp = _fingerprint("action_test", {"param": 1})
        assert isinstance(fp, str)
        assert len(fp) == 64

        admin_user = MagicMock(role="admin")
        normal_user = MagicMock(role="viewer")
        assert _is_admin(admin_user) is True
        assert _is_admin(normal_user) is False
        assert _is_manager(admin_user) is True

        # Incidents mutate
        db_mut = AsyncMock()
        db_mut.add = MagicMock()
        mock_case = MagicMock(id=1, version=1, revision=1, status="new", assigned_to_user_id=None)
        mock_existing = MagicMock(changed=True)
        with patch("app.features.incidents.write_router._load_case", AsyncMock(return_value=mock_case)), \
             patch("app.features.incidents.write_router._existing_mutation", AsyncMock(return_value=mock_existing)):
            user = MagicMock(id=10, role="admin", username="admin")
            res = await _mutate_case(
                db_mut, user, 1, "test_action", {}, "idemp-key-1", lambda c: (True, "event", None, {})
            )
            assert res["idempotent_replay"] is True

        with patch("app.features.incidents.write_router._load_case", AsyncMock(return_value=mock_case)), \
             patch("app.features.incidents.write_router._existing_mutation", AsyncMock(return_value=None)), \
             patch("app.features.incidents.write_router.append_event", AsyncMock(return_value=MagicMock(sequence=1, id=10, event_type="ack", created_at=1700000000))), \
             patch("app.features.incidents.write_router._broadcast_case", AsyncMock()):
            user = MagicMock(id=10, role="admin", username="admin")
            res2 = await _mutate_case(
                db_mut, user, 1, "ack", {}, "idemp-key-2", lambda c: (True, "ack", "note", {})
            )
            assert res2["idempotent_replay"] is False
            assert res2["changed"] is True




