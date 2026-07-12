"""Coordinate-frame helpers for GNSS adjustment outputs."""

from __future__ import annotations

import math

import numpy as np
from numpy.typing import NDArray


def ecef_to_llh(x: float, y: float, z: float) -> tuple[float, float, float]:
    """Convert WGS84 ECEF metres to latitude, longitude and ellipsoidal height."""

    a = 6378137.0
    f = 1 / 298.257223563
    e2 = 2 * f - f**2
    lon = math.atan2(y, x)
    p = math.hypot(x, y)
    lat = math.atan2(z, p * (1 - e2))
    height = 0.0
    for _ in range(8):
        sin_lat = math.sin(lat)
        n = a / math.sqrt(1 - e2 * sin_lat**2)
        height = p / max(math.cos(lat), 1e-15) - n
        next_lat = math.atan2(z, p * (1 - e2 * n / (n + height)))
        if abs(next_lat - lat) < 1e-13:
            lat = next_lat
            break
        lat = next_lat
    return math.degrees(lat), math.degrees(lon), height


def ecef_to_enu_rotation(latitude_deg: float, longitude_deg: float) -> NDArray[np.float64]:
    """Return the rotation matrix that maps ECEF deltas to local ENU deltas."""

    lat = math.radians(float(latitude_deg))
    lon = math.radians(float(longitude_deg))
    sin_lat, cos_lat = math.sin(lat), math.cos(lat)
    sin_lon, cos_lon = math.sin(lon), math.cos(lon)
    return np.asarray(
        [
            [-sin_lon, cos_lon, 0.0],
            [-sin_lat * cos_lon, -sin_lat * sin_lon, cos_lat],
            [cos_lat * cos_lon, cos_lat * sin_lon, sin_lat],
        ],
        dtype=float,
    )


def ecef_covariance_to_enu(
    covariance_ecef: NDArray[np.float64] | tuple[tuple[float, float, float], ...],
    latitude_deg: float,
    longitude_deg: float,
) -> NDArray[np.float64]:
    """Rotate a 3x3 ECEF covariance block into the ENU frame."""

    covariance = np.asarray(covariance_ecef, dtype=float)
    rotation = ecef_to_enu_rotation(latitude_deg, longitude_deg)
    return rotation @ covariance @ rotation.T


def enu_covariance_to_ecef(
    covariance_enu: NDArray[np.float64] | tuple[tuple[float, float, float], ...],
    latitude_deg: float,
    longitude_deg: float,
) -> NDArray[np.float64]:
    """Rotate a 3x3 ENU covariance block into the ECEF frame."""

    covariance = np.asarray(covariance_enu, dtype=float)
    rotation = ecef_to_enu_rotation(latitude_deg, longitude_deg)
    return rotation.T @ covariance @ rotation


def neu_standard_deviation_to_ecef_covariance(
    standard_deviation_neu: tuple[float, float, float],
    latitude_deg: float,
    longitude_deg: float,
) -> NDArray[np.float64]:
    """Convert independent N/E/U standard deviations to ECEF covariance."""

    north, east, up = (float(value) for value in standard_deviation_neu)
    covariance_enu = np.diag([east * east, north * north, up * up])
    return enu_covariance_to_ecef(covariance_enu, latitude_deg, longitude_deg)


def ecef_point_covariance_to_enu(
    covariance_ecef: NDArray[np.float64] | tuple[tuple[float, float, float], ...],
    ecef_point: tuple[float, float, float],
) -> NDArray[np.float64]:
    """Rotate a point covariance from ECEF into ENU using the point's geodetic latitude."""

    latitude_deg, longitude_deg, _ = ecef_to_llh(*ecef_point)
    return ecef_covariance_to_enu(covariance_ecef, latitude_deg, longitude_deg)


def covariance_standard_deviation(
    covariance: NDArray[np.float64] | tuple[tuple[float, float, float], ...]
) -> tuple[float, float, float]:
    """Return the per-axis standard deviation from a covariance block."""

    values = np.asarray(covariance, dtype=float)
    return tuple(
        float(math.sqrt(max(values[index, index], 0.0)))
        for index in range(3)
    )
