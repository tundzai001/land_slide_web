# backend/processors/geodetic.py
import math
import numpy as np
import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# WGS84 Ellipsoid
A_WGS84 = 6378137.0
F_WGS84 = 1 / 298.257223563
E2_WGS84 = 2 * F_WGS84 - F_WGS84**2

# VN2000 Ellipsoid (same as WGS84/GRS80)
A_VN2000 = 6378137.0
F_VN2000 = 1 / 298.257223563
E2_VN2000 = 2 * F_VN2000 - F_VN2000**2

# Standard VN2000 7-parameter transformation defaults (CORS-synced)
# Keep the same convention/signs as geodetic/agent_universal.py (RTCMDatum defaults)
DX = 191.90441429
DY = 39.30318279
DZ = 111.45032835
OM = 0.00928836 * (math.pi / (180.0 * 3600.0))   # rX (seconds to radians)
PH = -0.01975479 * (math.pi / (180.0 * 3600.0))  # rY
EP = 0.00427372 * (math.pi / (180.0 * 3600.0))   # rZ
SK = 0.999999747093722                             # Scale factor (1 + s*10^-6)

VN2000_PROVINCE_TABLE = [
    {"code": "AG_KG", "name": "An Giang + Kiên Giang", "l0_deg": 104.75, "k0": 0.9999, "aliases": ["an giang", "kien giang"]},
    {"code": "BN_BG", "name": "Bắc Ninh + Bắc Giang", "l0_deg": 107.0, "k0": 0.9999, "aliases": ["bac ninh", "bac giang"]},
    {"code": "CM_BL", "name": "Cà Mau + Bạc Liêu", "l0_deg": 104.5, "k0": 0.9999, "aliases": ["ca mau", "bac lieu"]},
    {"code": "CAO_BANG", "name": "Cao Bằng", "l0_deg": 105.75, "k0": 0.9999, "aliases": ["cao bang"]},
    {"code": "DAKLAK_PY", "name": "Đắk Lắk + Phú Yên", "l0_deg": 108.5, "k0": 0.9999, "aliases": ["dak lak", "phu yen"]},
    {"code": "DIEN_BIEN", "name": "Điện Biên", "l0_deg": 103.0, "k0": 0.9999, "aliases": ["dien bien"]},
    {"code": "DNAI_BPHUOC", "name": "Đồng Nai + Bình Phước", "l0_deg": 107.75, "k0": 0.9999, "aliases": ["dong nai", "binh phuoc"]},
    {"code": "DTHAP_TGIANG", "name": "Đồng Tháp + Tiền Giang", "l0_deg": 105.0, "k0": 0.9999, "aliases": ["dong thap", "tien giang"]},
    {"code": "GLAI_BDINH", "name": "Gia Lai + Bình Định", "l0_deg": 108.25, "k0": 0.9999, "aliases": ["gia lai", "binh dinh"]},
    {"code": "HA_TINH", "name": "Hà Tĩnh", "l0_deg": 105.5, "k0": 0.9999, "aliases": ["ha tinh"]},
    {"code": "HYEN_TBINH", "name": "Hưng Yên + Thái Bình", "l0_deg": 105.5, "k0": 0.9999, "aliases": ["hung yen", "thai binh"]},
    {"code": "KH_HOA_NTHUAN", "name": "Khánh Hòa + Ninh Thuận", "l0_deg": 108.25, "k0": 0.9999, "aliases": ["khanh hoa", "ninh thuan"]},
    {"code": "LAI_CHAU", "name": "Lai Châu", "l0_deg": 104.75, "k0": 0.9999, "aliases": ["lai chau"]},
    {"code": "LANG_SON", "name": "Lạng Sơn", "l0_deg": 107.25, "k0": 0.9999, "aliases": ["lang son"]},
    {"code": "LCAI_YBAI", "name": "Lào Cai + Yên Bái", "l0_deg": 104.75, "k0": 0.9999, "aliases": ["lao cai", "yen bai"]},
    {"code": "LDONG_DNONG_BTHUAN", "name": "Lâm Đồng + Đắk Nông + Bình Thuận", "l0_deg": 107.75, "k0": 0.9999, "aliases": ["lam dong", "dak nong", "binh thuan"]},
    {"code": "NGHE_AN", "name": "Nghệ An", "l0_deg": 104.75, "k0": 0.9999, "aliases": ["nghe an"]},
    {"code": "NBINH_HNAM_NDINH", "name": "Ninh Bình + Hà Nam + Nam Định", "l0_deg": 105.0, "k0": 0.9999, "aliases": ["ninh binh", "ha nam", "nam dinh"]},
    {"code": "PHU_THO_VPHUC_HBINH", "name": "Phú Thọ + Vĩnh Phúc + Hòa Bình", "l0_deg": 104.75, "k0": 0.9999, "aliases": ["phu tho", "vinh phuc", "hoa binh"]},
    {"code": "QNGAI_KTUM", "name": "Quảng Ngãi + Kon Tum", "l0_deg": 108.0, "k0": 0.9999, "aliases": ["quang ngai", "kon tum"]},
    {"code": "QNINH", "name": "Quảng Ninh", "l0_deg": 107.75, "k0": 0.9999, "aliases": ["quang ninh"]},
    {"code": "QTRI_QBINH", "name": "Quảng Trị + Quảng Bình", "l0_deg": 106.0, "k0": 0.9999, "aliases": ["quang tri", "quang binh"]},
    {"code": "SON_LA", "name": "Sơn La", "l0_deg": 104.0, "k0": 0.9999, "aliases": ["son la"]},
    {"code": "TNINH_LONGAN", "name": "Tây Ninh + Long An", "l0_deg": 105.75, "k0": 0.9999, "aliases": ["tay ninh", "long an"]},
    {"code": "TNGUYEN_BKAN", "name": "Thái Nguyên + Bắc Kạn", "l0_deg": 106.5, "k0": 0.9999, "aliases": ["thai nguyen", "bac kan"]},
    {"code": "THANH_HOA", "name": "Thanh Hóa", "l0_deg": 105.0, "k0": 0.9999, "aliases": ["thanh hoa"]},
    {"code": "CTHO_STRANG_HGIANG", "name": "Thành phố Cần Thơ + Sóc Trăng + Hậu Giang", "l0_deg": 105.0, "k0": 0.9999, "aliases": ["can tho", "soc trang", "hau giang"]},
    {"code": "DANANG_QNAM", "name": "Thành phố Đà Nẵng + Quảng Nam", "l0_deg": 107.75, "k0": 0.9999, "aliases": ["da nang", "quang nam"]},
    {"code": "HA_NOI", "name": "Thành phố Hà Nội", "l0_deg": 105.0, "k0": 0.9999, "aliases": ["ha noi", "hanoi"]},
    {"code": "HPHONG_HDUONG", "name": "Thành phố Hải Phòng + Hải Dương", "l0_deg": 105.75, "k0": 0.9999, "aliases": ["hai phong", "hai duong"]},
    {"code": "HCM_BRVT_BDUONG", "name": "Thành phố Hồ Chí Minh + Bà Rịa - Vũng Tàu + Bình Dương", "l0_deg": 105.75, "k0": 0.9999, "aliases": ["ho chi minh", "hcm", "ba ria", "vung tau", "binh duong"]},
    {"code": "HUE", "name": "Thành phố Huế", "l0_deg": 107.0, "k0": 0.9999, "aliases": ["hue", "thua thien hue"]},
    {"code": "TQUANG_HGIANG", "name": "Tuyên Quang + Hà Giang", "l0_deg": 106.0, "k0": 0.9999, "aliases": ["tuyen quang", "ha giang"]},
    {"code": "VLONG_BTRE_TVINH", "name": "Vĩnh Long + Bến Tre + Trà Vinh", "l0_deg": 105.5, "k0": 0.9999, "aliases": ["vinh long", "ben tre", "tra vinh"]},
]

from dataclasses import dataclass, field

def parse_vn2000_central_meridian(raw_value, default: float = 105.0) -> Tuple[float, str]:
    """Parse VN2000 central meridian.

    Operators often enter province meridians as compact degree-minute notation
    (104.45 means 104 degrees 45 minutes). Decimal-degree values such as 104.75
    remain valid and are returned unchanged.
    """
    if raw_value is None:
        return default, "default"

    raw = str(raw_value).strip().replace(",", ".")
    if not raw:
        return default, "default"

    import re
    dms_match = re.match(r"^([+-]?\d+(?:\.\d+)?)\s*(?:°|d|\s)\s*(\d+(?:\.\d+)?)\s*(?:'|m)?$", raw, re.I)
    if dms_match:
        deg = float(dms_match.group(1))
        minutes = float(dms_match.group(2))
        if 0 <= minutes < 60:
            sign = -1 if deg < 0 else 1
            return sign * (abs(deg) + minutes / 60.0), "deg_min"

    compact_match = re.match(r"^([+-]?\d+)\.(\d{2})$", raw)
    if compact_match:
        deg = float(compact_match.group(1))
        minutes = float(compact_match.group(2))
        if 0 < minutes < 60:
            sign = -1 if deg < 0 else 1
            return sign * (abs(deg) + minutes / 60.0), "deg_min_compact"

    try:
        return float(raw), "decimal_deg"
    except ValueError:
        return default, "default"

def normalize_vn2000_l0_value(value, default: float = 105.0) -> Tuple[float, str]:
    """Normalize stored VN2000 L0 values.

    Old configs stored the operator input directly as a number, so 104.45 was
    persisted as l0_deg=104.45 even though the intended survey notation was
    104 degrees 45 minutes. Known decimal-degree L0 values are preserved.
    """
    try:
        l0 = float(value)
    except (TypeError, ValueError):
        return default, "default"

    known_decimal_l0 = {
        103.0, 104.0, 104.5, 104.75, 105.0, 105.5, 105.75,
        106.0, 106.5, 107.0, 107.25, 107.75, 108.0, 108.25, 108.5
    }
    if any(abs(l0 - known) < 1e-9 for known in known_decimal_l0):
        return l0, "decimal_deg"

    deg = math.trunc(l0)
    minutes = round(abs(l0 - deg) * 100.0, 8)
    if 0 < minutes < 60:
        sign = -1 if l0 < 0 else 1
        return sign * (abs(deg) + minutes / 60.0), "legacy_deg_min_compact"

    return l0, "decimal_deg"

@dataclass
class DatumParams:
    """Transformation parameters from ITRF/WGS84 to VN2000 (standard or RTCM 1021/1023/1025)"""
    # 7-parameters (Helmert)
    dx: float = 191.90441429
    dy: float = 39.30318279
    dz: float = 111.45032835
    rx: float = 0.00928836   # arcseconds
    ry: float = -0.01975479  # arcseconds
    rz: float = 0.00427372   # arcseconds
    k: float = 0.999999747093722  # scale factor (1 + s*10^-6)
    
    # Projection
    l0_deg: float = 105.0
    k0: float = 0.9999
    false_e: float = 500000.0
    false_n: float = 0.0
    
    # Residuals (RTCM 1023/Local corrections)
    res_b: float = 0.0  # Latitude residual (radians)
    res_l: float = 0.0  # Longitude residual (radians)
    res_h: float = 0.0  # Height residual (meters)
    
    # Grid Shifts (Custom CORS shifts)
    res_n: float = 0.0  # North shift (meters)
    res_e: float = 0.0  # East shift (meters)
    res_h_shift: float = 0.0 # Height shift (meters)

class VN2000Converter:
    @staticmethod
    def llh_rad_to_ecef(phi: float, lam: float, h: float) -> Tuple[float, float, float]:
        a = A_WGS84
        e2 = E2_WGS84
        sin_phi = math.sin(phi)
        cos_phi = math.cos(phi)
        n = a / math.sqrt(1.0 - e2 * sin_phi * sin_phi)
        x = (n + h) * cos_phi * math.cos(lam)
        y = (n + h) * cos_phi * math.sin(lam)
        z = (n * (1.0 - e2) + h) * sin_phi
        return x, y, z

    @staticmethod
    def ecef_to_llh_rad(x: float, y: float, z: float) -> Tuple[float, float, float]:
        a = A_VN2000
        e2 = E2_VN2000
        p = math.sqrt(x * x + y * y)
        if p < 1e-12:
            lat = math.copysign(math.pi / 2.0, z)
            lon = 0.0
            h = abs(z) - a * math.sqrt(1 - e2)
            return lat, lon, h
        
        b = a * math.sqrt(1 - e2)
        ep2 = (a * a - b * b) / (b * b)
        theta = math.atan2(z * a, p * b)
        st = math.sin(theta)
        ct = math.cos(theta)
        lat = math.atan2(z + ep2 * b * st * st * st, p - e2 * a * ct * ct * ct)
        lon = math.atan2(y, x)
        sin_lat = math.sin(lat)
        n = a / math.sqrt(1.0 - e2 * sin_lat * sin_lat)
        h = p / math.cos(lat) - n
        return lat, lon, h

    @staticmethod
    def helmert_transform(x: float, y: float, z: float, p: DatumParams) -> Tuple[float, float, float]:
        """Apply 7-parameter Helmert transformation (Coordinate Frame Rotation convention)"""
        ro = math.pi / (180.0 * 3600.0) # arcsec to rad
        om = p.rx * ro
        ph = p.ry * ro
        ep = p.rz * ro
        k = p.k
        
        # Consistent with C# reference formula:
        # Xv = dX0 + k * (x + epsilon0 * y - phi0 * z)
        # Yv = dY0 + k * (-epsilon0 * x + y + omega0 * z)
        # Zv = dZ0 + k * (phi0 * x - omega0 * y + z)
        xv = p.dx + k * (x + ep * y - ph * z)
        yv = p.dy + k * (-ep * x + y + om * z)
        zv = p.dz + k * (ph * x - om * y + z)
        return xv, yv, zv

    @staticmethod
    def blh_to_xyh(phi: float, lam: float, h: float, p: DatumParams) -> Tuple[float, float, float]:
        """Gauss-Kruger Projection to NEH"""
        l0_rad = math.radians(p.l0_deg)
        a = A_VN2000
        e2 = E2_VN2000
        ep2 = e2 / (1.0 - e2)
        sin_phi = math.sin(phi)
        cos_phi = math.cos(phi)
        tan_phi = math.tan(phi)
        n = a / math.sqrt(1.0 - e2 * sin_phi * sin_phi)
        t = tan_phi * tan_phi
        c = ep2 * cos_phi * cos_phi
        A = (lam - l0_rad) * cos_phi
        e4 = e2 * e2
        e6 = e4 * e2
        
        m = a * (
            (1.0 - e2 / 4.0 - 3.0 * e4 / 64.0 - 5.0 * e6 / 256.0) * phi
            - (3.0 * e2 / 8.0 + 3.0 * e4 / 32.0 + 45.0 * e6 / 1024.0) * math.sin(2.0 * phi)
            + (15.0 * e4 / 256.0 + 45.0 * e6 / 1024.0) * math.sin(4.0 * phi)
            - (35.0 * e6 / 3072.0) * math.sin(6.0 * phi)
        )
        
        north = p.false_n + p.k0 * (
            m + n * tan_phi * (
                A * A / 2.0
                + (5.0 - t + 9.0 * c + 4.0 * c * c) * A**4 / 24.0
                + (61.0 - 58.0 * t + t * t + 600.0 * c - 330.0 * ep2) * A**6 / 720.0
            )
        )
        east = p.false_e + p.k0 * n * (
            A
            + (1.0 - t + c) * A**3 / 6.0
            + (5.0 - 18.0 * t + t * t + 72.0 * c - 58.0 * ep2) * A**5 / 120.0
        )
        return north, east, h

    @classmethod
    def wgs84_to_vn2000(cls, lat_deg: float, lon_deg: float, h: float, province_code: str = None, custom_params: DatumParams = None) -> Tuple[float, float, float]:
        """High-precision conversion from WGS84 LLH to VN2000 NEH"""
        # 0. Setup parameters
        p = custom_params if custom_params else DatumParams()
        
        # If no custom params but province code exists, override L0/k0
        if not custom_params and province_code:
            for province in VN2000_PROVINCE_TABLE:
                if province['code'] == province_code:
                    p.l0_deg = province['l0_deg']
                    p.k0 = province['k0']
                    break
        elif not custom_params:
            # Auto-infer L0
            p.l0_deg = min([103.0, 104.0, 104.5, 104.75, 105.0, 105.5, 105.75, 106.0, 106.5, 107.0, 107.25, 107.75, 108.0, 108.25, 108.5], 
                         key=lambda l: abs(l - lon_deg))

        # 1. WGS84 LLH -> ECEF
        xw, yw, zw = cls.llh_rad_to_ecef(math.radians(lat_deg), math.radians(lon_deg), h)

        # 2. 7-Parameter Helmert Transform (WGS84 -> VN2000 XYZ)
        xv, yv, zv = cls.helmert_transform(xw, yw, zw, p)

        # 3. VN2000 ECEF -> LLH (Target datum LLH)
        lat_v, lon_v, h_v = cls.ecef_to_llh_rad(xv, yv, zv)

        # 4. Apply Residuals (RTCM 1023)
        lat_v += p.res_b
        lon_v += p.res_l
        h_v += p.res_h

        # 5. Projection (Gauss-Kruger) -> NEH
        north, east, h_neh = cls.blh_to_xyh(lat_v, lon_v, h_v, p)

        # 6. Apply Grid Shifts (Shift CORS)
        north += p.res_n
        east += p.res_e
        h_neh += p.res_h_shift

        return north, east, h_neh
