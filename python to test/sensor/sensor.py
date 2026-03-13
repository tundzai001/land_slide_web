"""
Merged Sensor Reader — Rain Gauge + Water Level (+ bất kỳ GWL/RSB nào)
─────────────────────────────────────────────────────────────────────
Tính năng:
  • Đọc Modbus/RS485 qua nhiều cổng USB riêng biệt
    • RSL/RAIN: delta rain, cường độ (mm/h), tích lũy 1ph/5ph/1h/24h, reset nửa đêm
    • GWL / RSB / các loại khác: publish raw reading
  • Tự nhận dạng cổng USB — cắm sai thứ tự vẫn hoạt động
      → probe từng /dev/ttyUSBx bằng Modbus slave ID đã cấu hình
  • MQTT reconnect tự động + offline log backup + replay khi có mạng lại
  • Modbus device reconnect thread riêng per sensor
    • Config: cùng thư mục với sensor.py
"""

import glob
import json
import logging
import math
import os
import serial
import socket
import threading
import time
import configparser

from datetime import datetime, timedelta

import paho.mqtt.client as mqtt
from pymodbus.client import ModbusSerialClient

# Compatibility: một số môi trường chỉ có serial.Serial nhưng thiếu serial_for_url
# (pymodbus cần serial_for_url để mở cổng serial).
if not hasattr(serial, "serial_for_url") and hasattr(serial, "Serial"):
    def _serial_for_url(url, *args, **kwargs):
        return serial.Serial(url, *args, **kwargs)
    serial.serial_for_url = _serial_for_url


# ── Config ────────────────────────────────────────────────────────────────────
# strict=False: chấp nhận key trùng trong config.ini và dùng giá trị xuất hiện sau cùng
config = configparser.ConfigParser(strict=False)
script_dir = os.path.dirname(os.path.abspath(__file__))
home_dir = os.path.expanduser(f"~{os.getenv('SUDO_USER') or os.getenv('USER')}")
config.read(os.path.join(script_dir, "config.ini"))

# ── Runtime hardware state (populated by init_hardware()) ─────────────────────
_active_ports: dict = {}        # sensor_num (int) → port string actually in use
_active_unit_ids: dict = {}     # sensor_num (int) → detected modbus unit id
modbus_client_: dict = {}       # sensor_num → ModbusSerialClient
_rain_monitors: dict = {}       # sensor_num → RainGaugeMonitor
_last_clear_dates: dict = {}    # sensor_num → date of last midnight reset
_gwl_scan_once_done: set = set()  # sensor_num scanned once for register suggestions
_gwl_prev_scan_raw: dict = {}   # sensor_num → {addr: raw}

# ── MQTT + thread state ───────────────────────────────────────────────────────
try:
    mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
except Exception:
    mqtt_client = mqtt.Client()
log_thread = None
reconnect_thread = None
reconnect_device_thread: dict = {}


# ═══════════════════════════════════════════════════════════════════════════════
#  RAIN GAUGE CALCULATOR
# ═══════════════════════════════════════════════════════════════════════════════
class RainGaugeMonitor:
    def __init__(self):
        self.last_rain_value = None
        self.last_rain_timestamp = None
        self.total_rainfall = 0.0
        self.rain_data = []   # ordered oldest→newest; trimmed to 24 h

    def calculate_delta_rain(self, current_value, current_timestamp):
        if self.last_rain_value is None:
            self.last_rain_value = current_value
            self.last_rain_timestamp = current_timestamp
            return {
                'intensity_mmh': 0.0,
                'delta_rain': 0.0,
                'delta_time_seconds': 0.0,
                'status': 'initialized',
            }

        delta_rain = current_value - self.last_rain_value
        delta_time_seconds = current_timestamp - self.last_rain_timestamp

        if delta_rain > 0 and delta_time_seconds > 0:
            self.total_rainfall += delta_rain
            status = 'raining'
        elif delta_rain < 0:
            status = 'reset_detected'
            delta_rain = 0
        else:
            status = 'no_rain'

        self.last_rain_timestamp = current_timestamp
        self.last_rain_value = current_value
        return {
            'intensity_mmh': 0.0,
            'delta_rain': round(delta_rain, 4),
            'delta_time_seconds': round(delta_time_seconds, 2),
            'status': status,
        }

    def calculate_interval_rainfall(self):
        if not self.rain_data or len(self.rain_data) < 2:
            return None

        current_time = datetime.now()
        rainfall = {}

        minute_ago = current_time - timedelta(minutes=1)
        minute_rain = 0
        for data in reversed(self.rain_data):
            if datetime.fromisoformat(data['timestamp_str']) >= minute_ago:
                minute_rain += data.get('delta_rain', 0)
            else:
                break
        rainfall['last_minute'] = round(minute_rain, 4)

        five_minute_ago = current_time - timedelta(minutes=5)
        five_minute_rain = 0
        for data in reversed(self.rain_data):
            if datetime.fromisoformat(data['timestamp_str']) >= five_minute_ago:
                five_minute_rain += data.get('delta_rain', 0)
            else:
                break
        rainfall['last_5_minutes'] = round(five_minute_rain, 4)

        hour_ago = current_time - timedelta(hours=1)
        hour_rain = 0
        for data in reversed(self.rain_data):
            if datetime.fromisoformat(data['timestamp_str']) >= hour_ago:
                hour_rain += data.get('delta_rain', 0)
            else:
                break
        rainfall['last_hour'] = round(hour_rain, 4)

        day_ago = current_time - timedelta(days=1)
        day_rain = 0
        for data in reversed(self.rain_data):
            if datetime.fromisoformat(data['timestamp_str']) >= day_ago:
                day_rain += data.get('delta_rain', 0)
            else:
                break
        rainfall['last_24h'] = round(day_rain, 4)

        return rainfall


def is_rain_sensor_type(sensor_type: str) -> bool:
    return str(sensor_type or '').upper() in {'RAIN', 'RSL'}


def read_holding_registers_compat(client, address, count, unit_id):
    """Compat wrapper for different pymodbus versions."""
    attempts = [
        {"address": address, "count": count, "slave": unit_id},
        {"address": address, "count": count, "unit": unit_id},
        {"address": address, "count": count, "device_id": unit_id},
    ]

    last_error = None
    for kwargs in attempts:
        try:
            return client.read_holding_registers(**kwargs)
        except TypeError as exc:
            last_error = exc

    if last_error:
        raise last_error
    raise TypeError("No compatible read_holding_registers signature found")


def _try_autofind_gwl_register(client, base_address, unit_id, data_scale, offset, max_offset=10):
    """Try nearby holding registers and return the best plausible GWL candidate.

    Heuristic: reject tiny/status-like values, keep only physically plausible ranges,
    then pick the strongest candidate in the window.
    """
    candidates = []
    for off in range(-max_offset, max_offset + 1):
        if off == 0:
            continue
        addr = base_address + off
        if addr < 0:
            continue
        try:
            result = read_holding_registers_compat(client, addr, 1, unit_id)
            if not result or result.isError() or not result.registers:
                continue
            candidate_raw = float(result.registers[0])
            candidate_value = (candidate_raw * data_scale) + offset

            # Filter out tiny/status-like values and unrealistic levels.
            if candidate_raw < 10:
                continue
            if not (0.5 <= candidate_value <= 500.0):
                continue

            candidates.append((candidate_raw, addr, result.registers, candidate_value))
        except Exception:
            continue

    if not candidates:
        return None, None, None

    # Prefer larger raw among plausible candidates (often actual measurement register).
    candidates.sort(key=lambda x: x[0], reverse=True)
    best_raw, best_addr, best_regs, _best_value = candidates[0]
    return best_raw, best_addr, best_regs


def _scan_gwl_candidates(client, unit_id, data_scale, offset, start_addr=0, end_addr=60):
    """Scan a register range and return plausible (addr, raw, value) tuples."""
    candidates = []
    for addr in range(max(0, start_addr), max(0, end_addr) + 1):
        try:
            result = read_holding_registers_compat(client, addr, 1, unit_id)
            if not result or result.isError() or not result.registers:
                continue
            raw = float(result.registers[0])
            value = (raw * data_scale) + offset
            if raw < 1:
                continue
            if not (0.1 <= value <= 500.0):
                continue
            candidates.append((addr, raw, value))
        except Exception:
            continue
    return candidates


def _track_dynamic_gwl_register(sensor_id, current_addr, candidates, min_delta=1.0):
    """Select register whose raw value changes the most between scans."""
    prev = _gwl_prev_scan_raw.get(sensor_id)
    current_map = {addr: raw for addr, raw, _value in candidates}

    chosen_addr = current_addr
    chosen_raw = None

    if prev:
        best = None  # (delta, addr, raw)
        for addr, raw, _value in candidates:
            if addr not in prev:
                continue
            delta = abs(raw - prev[addr])
            if delta < min_delta:
                continue
            if best is None or delta > best[0]:
                best = (delta, addr, raw)
        if best is not None:
            _delta, chosen_addr, chosen_raw = best

    _gwl_prev_scan_raw[sensor_id] = current_map
    return chosen_addr, chosen_raw


def _filter_candidates_by_expected(candidates, expected_value, window):
    """Keep candidates whose converted value is near expected_value."""
    if expected_value is None:
        return candidates
    lo = expected_value - window
    hi = expected_value + window
    return [(a, r, v) for a, r, v in candidates if lo <= v <= hi]


def probe_first_alive_unit(client, address, count, candidate_unit_ids):
    """Return first unit_id that responds on this client, else None."""
    for unit_id in candidate_unit_ids:
        try:
            result = read_holding_registers_compat(client, address, count, unit_id)
            if result and (not result.isError()) and result.registers:
                return unit_id
        except Exception:
            continue
    return None


# ═══════════════════════════════════════════════════════════════════════════════
#  AUTO USB PORT DETECTION
# ═══════════════════════════════════════════════════════════════════════════════
def probe_and_remap_ports() -> tuple[dict, dict]:
    """
        Chế độ map cứng theo config:
        - Sensor n chỉ thử đúng MODBUS_PORT_n + MODBUS_UNIT_ID_n.
        - Không auto remap/hoán đổi giữa các sensor.
        - Nếu unit_id config không phản hồi, cho phép dò unit_id khác trên CHINH cổng đó.
        Trả về:
            - found_ports: {sensor_num: configured_port_or_none}
            - found_unit_ids: {sensor_num: configured_unit_id_or_none}
    """
    num = int(config['DEFAULT']['NUMBER_OF_SENSOR'])

    sensors = {}
    for i in range(num):
        snum = i + 1
        sensors[snum] = {
            'slave_id': int(config['DEFAULT'].get(f'MODBUS_UNIT_ID_{snum}', 1)),
            'baudrate': int(config['DEFAULT'].get(f'MODBUS_BAUDRATE_{snum}', 4800)),
            'address':  int(config['DEFAULT'].get(f'HOLDING_REGISTER_ADDRESS_{snum}', 0)),
            'count':    int(config['DEFAULT'].get(f'HOLDING_REGISTER_COUNT_{snum}', 1)),
            'config_port': config['DEFAULT'].get(f'MODBUS_PORT_{snum}', ''),
        }

    found = {snum: None for snum in sensors.keys()}
    found_unit_ids = {snum: None for snum in sensors.keys()}

    global_candidates = []
    for info in sensors.values():
        global_candidates.append(info['slave_id'])
    for fallback_uid in (1, 2, 3, 4):
        global_candidates.append(fallback_uid)

    # Keep order, remove duplicates.
    _seen = set()
    global_candidates = [uid for uid in global_candidates if not (uid in _seen or _seen.add(uid))]

    usb_ports = sorted(glob.glob('/dev/ttyUSB*'))
    print(f"[PROBE] Cổng USB tìm thấy: {usb_ports}")

    for snum, info in sensors.items():
        cfg_port = info['config_port']
        if not cfg_port:
            print(f"[PROBE] Sensor {snum}: thiếu MODBUS_PORT_{snum} -> DISABLED")
            continue

        if not os.path.exists(cfg_port):
            print(f"[PROBE] Sensor {snum} (slave_id={info['slave_id']}): {cfg_port} not found -> DISABLED")
            continue

        client = None
        try:
            client = ModbusSerialClient(port=cfg_port, baudrate=info['baudrate'])
            if not client.connect():
                print(f"[PROBE] Sensor {snum} (slave_id={info['slave_id']}): cannot open {cfg_port} -> DISABLED")
                continue

            result = read_holding_registers_compat(
                client,
                info['address'],
                info['count'],
                info['slave_id'],
            )
            if result and (not result.isError()) and result.registers:
                found[snum] = cfg_port
                found_unit_ids[snum] = info['slave_id']
                print(f"[PROBE] Sensor {snum} (slave_id={info['slave_id']}) -> {cfg_port}  [OK | STRICT]")
            else:
                detected_uid = probe_first_alive_unit(
                    client,
                    info['address'],
                    info['count'],
                    global_candidates,
                )
                if detected_uid is not None:
                    found[snum] = cfg_port
                    found_unit_ids[snum] = detected_uid
                    print(
                        f"[PROBE] Sensor {snum}: unit_id config={info['slave_id']} "
                        f"khong phan hoi, fallback unit_id={detected_uid} tren {cfg_port}  [STRICT-PORT]"
                    )
                else:
                    print(f"[PROBE] Sensor {snum} (slave_id={info['slave_id']}): no response on {cfg_port} -> DISABLED")
        except Exception:
            print(f"[PROBE] Sensor {snum} (slave_id={info['slave_id']}): read error on {cfg_port} -> DISABLED")
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass

    return found, found_unit_ids


# ═══════════════════════════════════════════════════════════════════════════════
#  HARDWARE INIT
# ═══════════════════════════════════════════════════════════════════════════════
def init_hardware():
    global _active_ports, _active_unit_ids, modbus_client_, _rain_monitors, _last_clear_dates
    _active_ports, _active_unit_ids = probe_and_remap_ports()
    num = int(config['DEFAULT']['NUMBER_OF_SENSOR'])
    for i in range(num):
        snum = i + 1
        port = _active_ports.get(snum, config['DEFAULT'].get(f'MODBUS_PORT_{snum}', ''))
        if not port:
            continue
        baud = int(config['DEFAULT'].get(f'MODBUS_BAUDRATE_{snum}', 4800))
        modbus_client_[snum] = ModbusSerialClient(port=port, baudrate=baud)
        if is_rain_sensor_type(config['DEFAULT'].get(f'SENSOR_TYPE_{snum}', '')):
            _rain_monitors[snum] = RainGaugeMonitor()
            _last_clear_dates[snum] = None


# ═══════════════════════════════════════════════════════════════════════════════
#  LOGGER
# ═══════════════════════════════════════════════════════════════════════════════
def initialize_logger(log_to_file=False):
    formatter = logging.Formatter('%(message)s')
    log = logging.getLogger()
    log.setLevel(logging.INFO)
    for handler in log.handlers[:]:
        log.removeHandler(handler)
    if log_to_file:
        log_file = os.path.join(home_dir, "Desktop", "backup_data.log")
        fh = logging.FileHandler(log_file, mode="a")
        fh.setLevel(logging.INFO)
        fh.setFormatter(formatter)
        log.addHandler(fh)
    else:
        ch = logging.StreamHandler()
        ch.setFormatter(formatter)
        log.addHandler(ch)


# ═══════════════════════════════════════════════════════════════════════════════
#  MQTT
# ═══════════════════════════════════════════════════════════════════════════════
def connect_mqtt():
    mqtt_password = config.get('DEFAULT', 'MQTT_PASSWORD', raw=True)
    MQTT_PORT = int(config['DEFAULT']['MQTT_PORT'])
    try:
        mqtt_client.username_pw_set(
            config['DEFAULT']['MQTT_USERNAME'],
            bytes(mqtt_password, "utf-8"),
        )
        mqtt_client.connect(config['DEFAULT']['MQTT_BROKER'], MQTT_PORT, 60)
        logging.info(f"Connected to MQTT Broker: {config['DEFAULT']['MQTT_BROKER']}")
    except Exception:
        return False
    return True


def publish_mqtt(message, ID, log_output=True):
    try:
        topic = config['DEFAULT'][f'MQTT_TOPIC_{ID}']
        mqtt_client.publish(topic, message)
        if log_output:
            logging.info(f"Published to {topic}: {message}")
    except Exception as e:
        logging.error(f"Failed to publish (sensor {ID}): {e}")


def reconnect():
    connected = False
    log_file = os.path.join(home_dir, "Desktop", "backup_data.log")
    while not connected:
        logging.info("MQTT disconnected. Retrying in 1 min...")
        if connect_mqtt():
            connected = True
            logging.info("MQTT reconnected.")
            if os.path.exists(log_file):
                send_log_file_to_mqtt(log_file)
                os.remove(log_file)
        else:
            time.sleep(60)


# ═══════════════════════════════════════════════════════════════════════════════
#  INTERNET
# ═══════════════════════════════════════════════════════════════════════════════
def internet(host="8.8.8.8", port=53, timeout=3):
    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
        return True
    except socket.error:
        return False


# ═══════════════════════════════════════════════════════════════════════════════
#  MODBUS
# ═══════════════════════════════════════════════════════════════════════════════
def modbus_connection(ID):
    port = _active_ports.get(ID, config['DEFAULT'].get(f'MODBUS_PORT_{ID}', ''))
    return bool(port) and os.path.exists(port)


def read_modbus_data(address, count, ID):
    try:
        modbus_client = modbus_client_.get(ID)
        if modbus_client is None:
            return None
        if not modbus_connection(ID):
            modbus_client.close()
            return None
        slave_id = _active_unit_ids.get(ID)
        if slave_id is None:
            slave_id = int(config['DEFAULT'].get(f'MODBUS_UNIT_ID_{ID}', 1))
        result = read_holding_registers_compat(modbus_client, address, count, slave_id)
        if result.isError() or not result.registers:
            return None
        registers = result.registers
        data_scale = float(config['DEFAULT'][f'DATA_SCALE_{ID}'])
        offset = float(config['DEFAULT'][f'OFFSET_{ID}'])

        # Prefer direct numeric register value to avoid fragile string slicing.
        raw_value = None
        if registers and len(registers) == 1:
            raw_value = float(registers[0])
        else:
            data_str = str(registers)
            fmt = config['DEFAULT'].get(f'RETURN_DATA_FORMAT_{ID}', '1,-1')
            start, end = map(int, fmt.split(','))
            raw_str = data_str[start:end] if end != 0 else data_str[start:]
            raw_value = float(raw_str.replace(',', '').replace(' ', ''))

        sensor_type = config['DEFAULT'].get(f'SENSOR_TYPE_{ID}', '').upper()
        scan_start = int(config['DEFAULT'].get(f'SCAN_START_ADDR_{ID}', 0))
        scan_end = int(config['DEFAULT'].get(f'SCAN_END_ADDR_{ID}', 60))

        # Dynamic tracking mode: pick register that actually changes when level changes.
        dynamic_track = config['DEFAULT'].get(f'DYNAMIC_GWL_TRACK_{ID}', '0') == '1'
        if dynamic_track and sensor_type in {'GWL', 'WATER', 'WL'} and count == 1:
            candidates = _scan_gwl_candidates(
                modbus_client,
                slave_id,
                data_scale,
                offset,
                start_addr=scan_start,
                end_addr=scan_end,
            )

            expected_str = config['DEFAULT'].get(f'EXPECTED_VALUE_{ID}', '').strip()
            expected_value = None
            if expected_str:
                try:
                    expected_value = float(expected_str)
                except Exception:
                    expected_value = None

            expected_window = float(config['DEFAULT'].get(f'DYNAMIC_EXPECTED_WINDOW_{ID}', 3.0))
            filtered = _filter_candidates_by_expected(candidates, expected_value, expected_window)
            if expected_value is not None and not filtered:
                logging.info(
                    f"[DYNAMIC-TRACK-SKIP] sensor {ID}: khong co candidate trong cua so "
                    f"target={expected_value} +/- {expected_window}. Giu nguyen addr={address}."
                )

            source_candidates = filtered if filtered else candidates
            min_delta = float(config['DEFAULT'].get(f'DYNAMIC_MIN_DELTA_{ID}', 1.0))
            best_addr, best_raw = _track_dynamic_gwl_register(ID, address, source_candidates, min_delta=min_delta)
            if best_raw is not None and best_addr != address:
                logging.info(
                    f"[DYNAMIC-TRACK] sensor {ID}: HOLDING_REGISTER_ADDRESS_{ID} "
                    f"{address} -> {best_addr}, raw={best_raw}"
                )
                config['DEFAULT'][f'HOLDING_REGISTER_ADDRESS_{ID}'] = str(best_addr)
                raw_value = best_raw
            elif ID not in _gwl_scan_once_done:
                _gwl_scan_once_done.add(ID)
                logging.info(
                    f"[DYNAMIC-TRACK] sensor {ID}: warm-up scan xong. "
                    f"Hay thay doi muc nuoc ro rang 1-2 lan de code bat dung thanh ghi dong."
                )

        auto_scan = config['DEFAULT'].get(f'AUTO_SCAN_GWL_ADDRESS_{ID}', '1') == '1'
        if (not dynamic_track) and auto_scan and sensor_type in {'GWL', 'WATER', 'WL'} and count == 1 and raw_value <= 1:
            expected_str = config['DEFAULT'].get(f'EXPECTED_VALUE_{ID}', '').strip()
            expected_value = None
            if expected_str:
                try:
                    expected_value = float(expected_str)
                except Exception:
                    expected_value = None

            candidates = _scan_gwl_candidates(
                modbus_client,
                slave_id,
                data_scale,
                offset,
                start_addr=scan_start,
                end_addr=scan_end,
            )

            if expected_value is not None and candidates:
                ranked = sorted(
                    candidates,
                    key=lambda x: abs(x[2] - expected_value),
                )
                best_addr, best_raw, best_value = ranked[0]
                tolerance = float(config['DEFAULT'].get(f'EXPECTED_TOLERANCE_{ID}', 0.5))
                delta = abs(best_value - expected_value)

                if delta <= tolerance:
                    logging.info(
                        f"[AUTO-FIX] sensor {ID}: HOLDING_REGISTER_ADDRESS_{ID} "
                        f"{address} -> {best_addr}, raw={best_raw}, value={best_value}, "
                        f"target={expected_value}, tolerance={tolerance}"
                    )
                    config['DEFAULT'][f'HOLDING_REGISTER_ADDRESS_{ID}'] = str(best_addr)
                    raw_value = best_raw
                else:
                    preview = ranked[:10]
                    logging.info(
                        f"[AUTO-FIX-SKIP] sensor {ID}: candidate gan nhat van lech target qua xa "
                        f"(best={best_value}, target={expected_value}, delta={round(delta,3)}, tol={tolerance})."
                    )
                    logging.info(
                        "[AUTO-FIX-SKIP] nearest candidates (addr,raw,value): "
                        + ", ".join([f"({a},{r},{round(v,3)})" for a, r, v in preview])
                    )
            elif ID not in _gwl_scan_once_done:
                _gwl_scan_once_done.add(ID)
                preview = sorted(candidates, key=lambda x: x[2], reverse=True)[:12]
                logging.info(
                    f"[SCAN] sensor {ID}: raw hien tai={raw_value} o addr={address}. "
                    f"Dat EXPECTED_VALUE_{ID}=gia tri thuc (vd 11.7) de auto-chon dung thanh ghi."
                )
                if preview:
                    logging.info(
                        "[SCAN] top candidates (addr,raw,value): "
                        + ", ".join([f"({a},{r},{round(v,3)})" for a, r, v in preview])
                    )
                else:
                    logging.info(f"[SCAN] sensor {ID}: khong tim thay candidate trong range {scan_start}..{scan_end}")

        value = (raw_value * data_scale) + offset

        if config['DEFAULT'].get(f'DEBUG_MODBUS_{ID}', '0') == '1':
            logging.info(
                f"[DEBUG] sensor {ID}: regs={registers}, raw={raw_value}, "
                f"scale={data_scale}, offset={offset}, value={value}"
            )

        return value
    except Exception as e:
        logging.error(f"read_modbus_data error (sensor {ID}): {e}")
        return None


def reconnect_device(address, count, ID):
    global reconnect_thread
    connected_device = False
    while not connected_device:
        msg = {
            "sensortype": config['DEFAULT'].get(f'SENSOR_TYPE_{ID}', ''),
            "sensorname":  config['DEFAULT'].get(f'SENSOR_NAME_{ID}', ''),
            "modbus_id":   config['DEFAULT'].get(f'MODBUS_UNIT_ID_{ID}', ''),
            "timestamp":   time.time(),
            "status": "Lost connection to Modbus Sensor. Trying to reconnect after 1 minute...",
        }
        if internet():
            logging.info(f"Lost Modbus connection to sensor {ID}. Retrying in 1 min...")
            publish_mqtt(json.dumps(msg), ID)
        else:
            logging.info(f"No internet. Lost Modbus connection to sensor {ID}.")
            if reconnect_thread is None or not reconnect_thread.is_alive():
                reconnect_thread = threading.Thread(target=reconnect, daemon=True)
                reconnect_thread.start()
        if read_modbus_data(address, count, ID) is not None:
            publish_mqtt(json.dumps({"status": "Reconnected to Modbus device successfully"}), ID)
            connected_device = True
        else:
            time.sleep(60)


# ═══════════════════════════════════════════════════════════════════════════════
#  OFFLINE LOG
# ═══════════════════════════════════════════════════════════════════════════════
def send_log_file_to_mqtt(log_file_path):
    try:
        with open(log_file_path, "r") as f:
            for line in f:
                if not internet():
                    reconnect()
                try:
                    data = json.loads(line)
                    sensor_id = data.get("modbus_id")
                    topic = config['DEFAULT'].get(f'MQTT_TOPIC_{sensor_id}', 'modbus_error')
                except Exception as e:
                    topic = 'modbus_error'
                    logging.error(e)
                mqtt_client.publish(topic, line.strip())
                time.sleep(0.5)
    except FileNotFoundError:
        logging.error(f"Log file not found: {log_file_path}")
    except Exception as e:
        logging.error(f"Error sending log: {e}")


def write_data_to_log():
    global reconnect_device_thread
    latency = int(config['DEFAULT']['READ_DATA_INTERVAL'])
    while not internet():
        for x in range(int(config['DEFAULT']['NUMBER_OF_SENSOR'])):
            snum = x + 1
            initialize_logger(log_to_file=True)
            raw = read_modbus_data(
                int(config['DEFAULT'].get(f'HOLDING_REGISTER_ADDRESS_{snum}', 0)),
                int(config['DEFAULT'].get(f'HOLDING_REGISTER_COUNT_{snum}', 1)),
                snum,
            )
            sensor_type = config['DEFAULT'].get(f'SENSOR_TYPE_{snum}', '').upper()
            if raw is None:
                initialize_logger(log_to_file=False)
                if modbus_connection(snum) and (x not in reconnect_device_thread or not reconnect_device_thread[x].is_alive()):
                    reconnect_device_thread[x] = threading.Thread(
                        target=reconnect_device,
                        name=f"ReconnectDeviceThread_{snum}",
                        args=(
                            int(config['DEFAULT'].get(f'HOLDING_REGISTER_ADDRESS_{snum}', 0)),
                            int(config['DEFAULT'].get(f'HOLDING_REGISTER_COUNT_{snum}', 1)),
                            snum,
                        ),
                        daemon=True,
                    )
                    reconnect_device_thread[x].start()
            else:
                if is_rain_sensor_type(sensor_type):
                    message = build_rain_message(snum, raw, print_to_console=False)
                else:
                    message = {
                        "sensortype": sensor_type,
                        "sensorname":  config['DEFAULT'].get(f'SENSOR_NAME_{snum}', ''),
                        "modbus_id":   config['DEFAULT'].get(f'MODBUS_UNIT_ID_{snum}', ''),
                        "timestamp":   time.time(),
                        "value":       raw,
                        "status":      "Normal",
                    }
                logging.info(json.dumps(message))
                time.sleep(latency)


# ═══════════════════════════════════════════════════════════════════════════════
#  RAIN HELPERS
# ═══════════════════════════════════════════════════════════════════════════════
def build_rain_message(sensor_num: int, raw_value: float,
                       print_to_console: bool = True) -> dict:
    monitor = _rain_monitors[sensor_num]
    ts = time.time()
    intensity_data = monitor.calculate_delta_rain(raw_value, ts)
    timestamp_str  = datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
    timestamp_iso  = datetime.now().isoformat(timespec="seconds")

    monitor.rain_data.append({
        'timestamp':          ts,
        'timestamp_str':      timestamp_str,
        'rain_value_mm':      raw_value,
        'delta_rain':         intensity_data['delta_rain'],
        'intensity_mmh':      intensity_data['intensity_mmh'],
        'delta_time_seconds': intensity_data['delta_time_seconds'],
        'calculation_status': intensity_data['status'],
        'total_rainfall':     monitor.total_rainfall,
    })
    # Trim to 24 h
    cutoff = ts - 86400
    monitor.rain_data = [d for d in monitor.rain_data if d['timestamp'] >= cutoff]

    interval_rainfall = monitor.calculate_interval_rainfall()
    intensity_avg = round(interval_rainfall['last_5_minutes'] * 12, 2) if interval_rainfall else 0.0

    # Daily reset at midnight
    now = datetime.now()
    if now.hour == 0 and now.minute == 0 and _last_clear_dates.get(sensor_num) != now.date():
        clear_rain_gauge(sensor_num)
        _last_clear_dates[sensor_num] = now.date()

    message = {
        "sensortype":     config['DEFAULT'].get(f'SENSOR_TYPE_{sensor_num}', 'RSL').upper(),
        "sensorname":     config['DEFAULT'].get(f'SENSOR_NAME_{sensor_num}', f'RAIN_{sensor_num}'),
        "modbus_id":      config['DEFAULT'].get(f'MODBUS_UNIT_ID_{sensor_num}', ''),
        "timestamp":      timestamp_iso,
        "rainfall_mm":    round(raw_value, 2),
        "intensity_mm_h": intensity_avg,
        "status":         intensity_data['status'],
    }

    if print_to_console:
        print(json.dumps(message, ensure_ascii=False))

    return message


def clear_rain_gauge(sensor_num: int):
    """Gửi lệnh Modbus FC06 để reset tích lũy mưa về 0."""
    port     = _active_ports.get(sensor_num, config['DEFAULT'].get(f'MODBUS_PORT_{sensor_num}', ''))
    baudrate = int(config['DEFAULT'].get(f'MODBUS_BAUDRATE_{sensor_num}', 4800))
    # FC06 Write Single Register: addr=0x0000 value=0x005A CRC=0x09F1
    frame = bytes.fromhex('01060000005A09F1')
    try:
        ser = serial.Serial(port, baudrate=baudrate, bytesize=8,
                            parity='N', stopbits=1, timeout=1)
        print(f"[RAIN] Sending daily precipitation clear to sensor {sensor_num}...")
        ser.write(frame)
        time.sleep(0.1)
        reply = ser.read(8)
        if reply == frame:
            logging.info(f"[RAIN] Sensor {sensor_num}: precipitation cleared successfully.")
        else:
            logging.warning(f"[RAIN] Sensor {sensor_num}: unexpected clear reply: {reply.hex(' ').upper()}")
        ser.close()
    except Exception as e:
        logging.error(f"clear_rain_gauge sensor {sensor_num}: {e}")


def get_rain_summary(sensor_num: int):
    """Thống kê phiên đo mưa hiện tại."""
    monitor = _rain_monitors.get(sensor_num)
    if not monitor or not monitor.rain_data:
        return "No rain data available"
    summary = {
        'total_rainfall_mm': round(monitor.total_rainfall, 4),
        'total_records':     len(monitor.rain_data),
        'start_time':        monitor.rain_data[0]['timestamp_str'],
        'end_time':          monitor.rain_data[-1]['timestamp_str'],
    }
    if len(monitor.rain_data) > 1:
        duration_s = monitor.rain_data[-1]['timestamp'] - monitor.rain_data[0]['timestamp']
        summary['duration_hours'] = round(duration_s / 3600, 2)
        summary['average_intensity_mmh'] = (
            round(monitor.total_rainfall / (duration_s / 3600), 4)
            if duration_s > 0 else 0
        )
    return summary


def save_rain_to_file(sensor_num: int, data: dict, filename="rain_data.json"):
    """Lưu bản ghi mưa ra file JSON (backup cục bộ)."""
    try:
        with open(filename, 'a') as f:
            json.dump(data, f)
            f.write('\n')
    except Exception as e:
        logging.error(f"save_rain_to_file sensor {sensor_num}: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════════
def main():
    global log_thread, reconnect_thread, reconnect_device_thread

    initialize_logger(log_to_file=False)

    # 1. Probe USB + init Modbus clients
    init_hardware()

    # 2. Connect MQTT
    latency = int(config['DEFAULT']['READ_DATA_INTERVAL'])
    connect_mqtt()

    # 3. Startup info
    num = int(config['DEFAULT']['NUMBER_OF_SENSOR'])
    print("=" * 60)
    print("Sensor reader started.")
    for i in range(num):
        snum  = i + 1
        stype = config['DEFAULT'].get(f'SENSOR_TYPE_{snum}', '?').upper()
        port  = _active_ports.get(snum) or 'DISABLED'
        topic = config['DEFAULT'].get(f'MQTT_TOPIC_{snum}', '?')
        slave = _active_unit_ids.get(snum) or config['DEFAULT'].get(f'MODBUS_UNIT_ID_{snum}', '?')
        print(f"  Sensor {snum}: type={stype}  slave_id={slave}  port={port}  topic={topic}")
    print("=" * 60)

    # 4. Main read loop
    while True:
        for x in range(num):
            snum        = x + 1
            sensor_type = config['DEFAULT'].get(f'SENSOR_TYPE_{snum}', '').upper()
            addr  = int(config['DEFAULT'].get(f'HOLDING_REGISTER_ADDRESS_{snum}', 0))
            count = int(config['DEFAULT'].get(f'HOLDING_REGISTER_COUNT_{snum}', 1))

            if not modbus_connection(snum):
                continue

            raw = read_modbus_data(addr, count, snum)

            if raw is None:
                initialize_logger(log_to_file=False)
                if x not in reconnect_device_thread or not reconnect_device_thread[x].is_alive():
                    reconnect_device_thread[x] = threading.Thread(
                        target=reconnect_device,
                        name=f"ReconnectDeviceThread_{snum}",
                        args=(addr, count, snum),
                        daemon=True,
                    )
                    reconnect_device_thread[x].start()
                continue

            if is_rain_sensor_type(sensor_type):
                message = build_rain_message(snum, raw, print_to_console=True)
            else:
                message = {
                    "sensortype": sensor_type,
                    "sensorname":  config['DEFAULT'].get(f'SENSOR_NAME_{snum}', ''),
                    "modbus_id":   config['DEFAULT'].get(f'MODBUS_UNIT_ID_{snum}', ''),
                    "timestamp":   time.time(),
                    "value":       raw,
                    "status":      "Normal",
                }

            if internet():
                initialize_logger(log_to_file=False)
                publish_mqtt(json.dumps(message), snum, log_output=(not is_rain_sensor_type(sensor_type)))
            else:
                if log_thread is None or not log_thread.is_alive():
                    log_thread = threading.Thread(target=write_data_to_log, daemon=True)
                    log_thread.start()
                if reconnect_thread is None or not reconnect_thread.is_alive():
                    reconnect_thread = threading.Thread(target=reconnect, daemon=True)
                    reconnect_thread.start()

            time.sleep(latency)


if __name__ == "__main__":
    main()
