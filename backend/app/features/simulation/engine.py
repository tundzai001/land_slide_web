"""Deterministic landslide scenario engine used by API and reports."""
from __future__ import annotations

import math
import random
from typing import Any

ENGINE_VERSION = "2.0.0"
SCHEMA_VERSION = 1

DEFAULT_PARAMETERS = {
    "cohesion": 15.0,
    "friction_angle": 30.0,
    "unit_weight": 18.0,
    "slip_depth": 5.0,
    "slope_angle": 25.0,
    "rainfall": 0.0,
    "pore_pressure_ratio": 0.0,
    "seismic_coeff": 0.0,
    "house_count": 40,
    "tree_count": 300,
    "ks": 1.5e-5,
    "porosity": 0.25,
    "fos_warning": 1.5,
    "fos_critical": 1.0,
}

PARAMETER_RANGES = {
    "cohesion": (0.0, 200.0), "friction_angle": (1.0, 60.0),
    "unit_weight": (5.0, 30.0), "slip_depth": (0.5, 50.0),
    "slope_angle": (1.0, 70.0), "rainfall": (0.0, 500.0),
    "pore_pressure_ratio": (0.0, 0.6), "seismic_coeff": (0.0, 0.5),
    "house_count": (0, 2000), "tree_count": (0, 10000),
    "ks": (1e-9, 1e-2), "porosity": (0.05, 0.7),
    "fos_warning": (1.0, 3.0), "fos_critical": (0.1, 1.5),
}


def normalize_parameters(values: dict[str, Any] | None) -> dict[str, float | int]:
    raw = {**DEFAULT_PARAMETERS, **(values or {})}
    normalized: dict[str, float | int] = {}
    for key, default in DEFAULT_PARAMETERS.items():
        try:
            value = float(raw[key])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Tham số {key} không phải là số") from exc
        low, high = PARAMETER_RANGES[key]
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"Tham số {key} phải nằm trong khoảng {low}–{high}")
        normalized[key] = int(round(value)) if key in {"house_count", "tree_count"} else value
    if normalized["fos_critical"] >= normalized["fos_warning"]:
        raise ValueError("Ngưỡng FoS nguy hiểm phải nhỏ hơn ngưỡng cảnh báo")
    return normalized


def calculate_fos(params: dict[str, float | int], ru: float | None = None) -> float:
    c = float(params["cohesion"])
    phi = math.radians(float(params["friction_angle"]))
    gamma = float(params["unit_weight"])
    depth = float(params["slip_depth"])
    slope = float(params["slope_angle"])
    pore_ratio = min(0.6, max(0.0, float(params["pore_pressure_ratio"] if ru is None else ru)))
    kh = max(0.0, float(params["seismic_coeff"]))
    slices, length = 20, 60.0
    dx = length / slices
    resisting = driving = 0.0
    for index in range(slices):
        x_ratio = index / slices
        alpha = math.radians(max(5.0, slope + 15.0 * (1.0 - 2.0 * x_ratio)))
        slice_depth = depth * math.sin(x_ratio * math.pi)
        if slice_depth < 0.1:
            continue
        weight = gamma * slice_depth * dx
        base_length = dx / math.cos(alpha)
        pore_pressure = pore_ratio * gamma * slice_depth
        normal_stress = weight * math.cos(alpha) / base_length
        effective_stress = max(0.0, normal_stress - pore_pressure)
        resisting += (c + effective_stress * math.tan(phi)) * base_length
        driving += weight * math.sin(alpha) + kh * weight * math.cos(alpha)
    return 99.0 if driving <= 0 else max(0.0, resisting / driving)


def _terrain_profile(params: dict[str, float | int]) -> list[dict[str, float]]:
    slope = math.radians(float(params["slope_angle"]))
    depth = float(params["slip_depth"])
    result = []
    for x in range(0, 121, 2):
        elevation = max(0.0, (60.0 - min(x, 60.0)) * math.tan(slope))
        taper = math.sin(math.pi * min(x, 60.0) / 60.0) if x <= 60 else 0.0
        result.append({"x_m": float(x), "elevation_m": round(elevation, 4), "slip_elevation_m": round(elevation - depth * taper, 4)})
    return result


def run_simulation(parameters: dict[str, Any] | None, duration_seconds: int, seed: int) -> dict[str, Any]:
    if not 3600 <= duration_seconds <= 604800:
        raise ValueError("Thời lượng mô phỏng phải từ 1 đến 168 giờ")
    params = normalize_parameters(parameters)
    rng = random.Random(seed)
    dt = 30.0
    sample_every = max(60, math.ceil(duration_seconds / 2000 / 60) * 60)
    next_sample = 0.0
    wetting_depth = cumulative_rain = 0.0
    state, critical_seconds = "STABLE", 0.0
    slide_start: float | None = None
    velocity = position = acceleration = 0.0
    volume = 20.0 * 30.0 * float(params["slip_depth"])
    mass = volume * float(params["unit_weight"]) * 100.0
    max_velocity = max_acceleration = 0.0
    min_fos = calculate_fos(params)
    events = [{"time_s": 0, "state": state, "label": "Bắt đầu mô phỏng"}]
    series: list[dict[str, Any]] = []
    house_thresholds = sorted(rng.uniform(12.0, 120.0) for _ in range(int(params["house_count"])))
    tree_thresholds = sorted(rng.uniform(4.0, 120.0) for _ in range(int(params["tree_count"])))
    peak_energy = 0.0

    elapsed = 0.0
    while elapsed <= duration_seconds:
        rain_m_s = float(params["rainfall"]) / 1000.0 / 3600.0
        ks = float(params["ks"])
        porosity = float(params["porosity"])
        if rain_m_s > 0:
            cumulative_rain += rain_m_s * dt
            if rain_m_s <= ks:
                infiltration = rain_m_s
            else:
                infiltration = min(rain_m_s, ks * (1.0 + 0.3 / max(0.01, wetting_depth)))
            wetting_depth += infiltration * dt / porosity
        else:
            # Drain rather than adding water (the browser engine had the sign wrong).
            wetting_depth = max(0.0, wetting_depth - ks * 0.1 * dt / porosity)
        infiltration_ru = 0.0
        if wetting_depth > float(params["slip_depth"]) * 0.3:
            water_head = wetting_depth - float(params["slip_depth"]) * 0.3
            infiltration_ru = min(0.6, water_head / float(params["slip_depth"]) * 0.5)
        effective_ru = min(0.6, float(params["pore_pressure_ratio"]) + infiltration_ru)
        fos = calculate_fos(params, effective_ru)
        min_fos = min(min_fos, fos)

        previous_state = state
        if state not in {"SLIDING", "DEPOSITED"}:
            if fos >= float(params["fos_warning"]):
                state, critical_seconds = "STABLE", 0.0
            elif fos >= float(params["fos_critical"]):
                state, critical_seconds = "WARNING", 0.0
            else:
                state, critical_seconds = "CRITICAL", critical_seconds + dt
                if critical_seconds >= 120.0:
                    state, slide_start = "SLIDING", elapsed

        if state == "SLIDING":
            slope = max(0.0, math.radians(float(params["slope_angle"])) - position * 0.006)
            mu = math.tan(math.radians(float(params["friction_angle"]) - 10.0))
            xi = 300.0
            if effective_ru > 0.3:
                mu, xi = max(0.05, mu * (1.0 - effective_ru)), 500.0
            height = max(0.5, float(params["slip_depth"]) * max(0.25, 1.0 - position / 5000.0))
            acceleration = 9.81 * math.sin(slope) - mu * 9.81 * math.cos(slope) - 9.81 * velocity * velocity / (xi * height)
            if velocity <= 0.01 and acceleration < 0:
                acceleration = velocity = 0.0
            velocity = max(0.0, velocity + acceleration * dt)
            position += velocity * dt
            if velocity > 1.0:
                added = 0.8 * velocity * dt
                volume += added
                mass += added * float(params["unit_weight"]) * 100.0
            max_velocity = max(max_velocity, velocity)
            max_acceleration = max(max_acceleration, acceleration)
            peak_energy = max(peak_energy, 0.5 * mass * velocity * velocity)
            if (slide_start is not None and elapsed - slide_start >= 300.0) or (elapsed > (slide_start or 0) + dt and velocity < 0.1):
                state, velocity, acceleration = "DEPOSITED", 0.0, 0.0

        if state != previous_state:
            events.append({"time_s": round(elapsed), "state": state, "label": {"WARNING": "FoS vào vùng cảnh báo", "CRITICAL": "FoS dưới ngưỡng nguy hiểm", "SLIDING": "Bắt đầu trượt", "DEPOSITED": "Khối trượt dừng"}.get(state, "Trở lại ổn định")})

        if elapsed >= next_sample or elapsed >= duration_seconds:
            houses = sum(value <= position for value in house_thresholds)
            trees = sum(value <= position for value in tree_thresholds)
            series.append({
                "time_s": round(min(elapsed, duration_seconds)), "state": state,
                "rainfall_mm_h": round(float(params["rainfall"]), 4),
                "cumulative_rain_mm": round(cumulative_rain * 1000.0, 4),
                "wetting_depth_m": round(wetting_depth, 6), "pore_pressure_ratio": round(effective_ru, 6),
                "fos": round(fos, 6), "velocity_m_s": round(velocity, 6),
                "acceleration_m_s2": round(acceleration, 6), "runout_m": round(position, 4),
                "volume_m3": round(volume, 4), "houses_affected": houses, "trees_affected": trees,
            })
            next_sample += sample_every
        elapsed += dt

    final = series[-1]
    classification = "Ổn định" if min_fos >= float(params["fos_warning"]) else "Cảnh báo" if min_fos >= float(params["fos_critical"]) else "Mất ổn định"
    if any(event["state"] == "SLIDING" for event in events):
        classification = "Đã xảy ra trượt mô phỏng"
    summary = {
        "classification": classification, "initial_fos": round(series[0]["fos"], 4), "minimum_fos": round(min_fos, 4),
        "slide_start_time_s": next((event["time_s"] for event in events if event["state"] == "SLIDING"), None),
        "max_velocity_m_s": round(max_velocity, 4), "max_acceleration_m_s2": round(max_acceleration, 4),
        "runout_m": final["runout_m"], "final_volume_m3": final["volume_m3"], "peak_kinetic_energy_j": round(peak_energy, 2),
        "houses_affected": final["houses_affected"], "trees_affected": final["trees_affected"], "final_state": final["state"],
        "sample_interval_s": sample_every, "sample_count": len(series),
    }
    return {"parameters": params, "time_series": series, "events": events, "summary": summary, "terrain_profile": _terrain_profile(params)}
