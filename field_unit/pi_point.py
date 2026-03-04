#!/usr/bin/env python3
import json
import logging
import time
import threading
import sys
import os
from pathlib import Path

# =====================================================
# IMPORTS
# =====================================================
try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("❌ paho-mqtt not installed. Run: pip install paho-mqtt")
    sys.exit(1)

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    print("⚠️  RPi.GPIO not installed or not running on Pi. GPIO will be simulated.")
    GPIO_AVAILABLE = False

# =====================================================
# CONFIGURATION
# =====================================================
LIGHT_PIN = 17  # GPIO 17 (physical pin 11)
ACTIVE_HIGH = True

# Default MQTT
MQTT_BROKER = "aitogy.asia"
MQTT_PORT = 1883
MQTT_USERNAME = "mqttUser"
MQTT_PASSWORD = ""

LOCAL_CONFIG = Path.home() / ".landslide_point.json"
BACKEND_URL = os.getenv('BACKEND_URL', 'https://monitoring.aitogy.com')

# Runtime values
DEVICE_CODE = None
MY_STATION_ID = 0

# Flag to prevent standard 15s pulse from turning off a continuous IMU siren
is_continuous_alert = False

logging.basicConfig(level=logging.INFO, format='%(asctime)s - PI_POINT - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# =====================================================
# GPIO CONTROL
# =====================================================
def gpio_setup():
    if GPIO_AVAILABLE:
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        GPIO.setup(LIGHT_PIN, GPIO.OUT)
        GPIO.output(LIGHT_PIN, GPIO.LOW if ACTIVE_HIGH else GPIO.HIGH)
        logger.info(f"✅ GPIO {LIGHT_PIN} initialized (active_high={ACTIVE_HIGH})")
    else:
        logger.info("⚠️ Simulating GPIO setup")

def light_on():
    logger.info(f"💡 Light ON (GPIO {LIGHT_PIN})")
    if GPIO_AVAILABLE:
        GPIO.output(LIGHT_PIN, GPIO.HIGH if ACTIVE_HIGH else GPIO.LOW)

def light_off():
    logger.info(f"💡 Light OFF (GPIO {LIGHT_PIN})")
    if GPIO_AVAILABLE:
        GPIO.output(LIGHT_PIN, GPIO.LOW if ACTIVE_HIGH else GPIO.HIGH)

def light_pulse(duration: int = 10):
    """Bật sáng một lúc rồi tắt"""
    global is_continuous_alert
    light_on()
    time.sleep(duration)
    # Check flag before turning off, so we don't accidentally silence a critical IMU siren
    if not is_continuous_alert:
        light_off()

def gpio_cleanup():
    if GPIO_AVAILABLE:
        GPIO.output(LIGHT_PIN, GPIO.LOW if ACTIVE_HIGH else GPIO.HIGH)
        GPIO.cleanup()
        logger.info("✅ GPIO cleaned up")

# =====================================================
# LICENSE UTILS
# =====================================================
def get_license_code_from_string(string_number: str) -> str:
    try:
        import math
        length = len(string_number)
        if length == 0: return ""
        arr = [0] * (length + 1)
        narr = [0.0] * (length + 1)
        number = float(string_number)
        r_string = ""
        n = length
        number *= n
        arr[0] = int(number * (10.0 ** -float(n)))
        for i in range(1, length):
            number = number - float(arr[i - 1]) / (10.0 ** -float(n))
            n -= 1
            arr[i] = int(number * (10 ** -float(n)))
        arr[length] = (arr[length - 2] + arr[length - 1]) / 2 + 1
        narr[0] = float(arr[0])
        for i in range(1, length + 1):
            narr[i] = (narr[i - 1] + float(arr[i])) / 2.0
        for i in range(length):
            A = narr[i + 1] * math.exp(-0.2)
            B = 0
            try:
                if arr[length] > 0 and arr[i + 1] > 0:
                    B = (math.log(arr[length], 10)) * math.pow(arr[i + 1], 0.2)
            except Exception:
                B = 0
            r_string += str(int(round(A + B)))
        return r_string
    except Exception:
        return ""

def generate_pi_license_base(serial_number: str) -> str:
    base_code_str = ""
    temp_str = ""
    s_number_part = serial_number[-10:]
    for c in s_number_part:
        temp_str += c.upper() if 'a' <= c.lower() <= 'z' else c
    for char in temp_str:
        base_code_str += str(ord(char))
    return base_code_str[:12] if len(base_code_str) > 12 else base_code_str.ljust(12, '0')

def generate_customer_license_base(identifier: str = "CUSTOMER") -> str:
    base_code_str = ""
    for char in identifier.upper():
        base_code_str += str(ord(char))
    return base_code_str[:12] if len(base_code_str) > 12 else base_code_str.ljust(12, '0')

# =====================================================
# REGISTRATION & CONFIG
# =====================================================
def auto_register_device():
    global DEVICE_CODE
    try:
        import requests
    except ImportError:
        logger.warning("⚠️ requests not installed - skipping register.")
        return

    try:
        existing_cfg = {}
        if LOCAL_CONFIG.exists():
            with open(LOCAL_CONFIG, 'r', encoding='utf-8') as f:
                existing_cfg = json.load(f)

        prefix = "fp" # Field Point
        serial = existing_cfg.get('device_code') or DEVICE_CODE or os.getenv('DEVICE_CODE') or f"{prefix}-{int(time.time())}"
        device_name = os.getenv('DEVICE_NAME', f'Point-{serial[-8:]}')
        DEVICE_CODE = serial

        url = f"{BACKEND_URL}/api/field/register"
        payload = {'serial': serial, 'name': device_name, 'device_type': 'pi_point'}

        logger.info(f"📡 Registering Point to {url} (serial={serial})")
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()

        result = resp.json()
        device_id = result.get('device_id')
        status = result.get('status', 'pending')
        station_id = result.get('station_id') or 0

        logger.info(f"✅ Registration: status={status}, station={station_id}")

        cfg = {**existing_cfg, 'device_code': serial, 'device_id': device_id, 'station_id': station_id}
        with open(LOCAL_CONFIG, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)

    except Exception as e:
        logger.warning(f"⚠️ Registration failed: {e}")

def load_local_config():
    global DEVICE_CODE, MY_STATION_ID, MQTT_BROKER, MQTT_PORT, MQTT_USERNAME, MQTT_PASSWORD
    if LOCAL_CONFIG.exists():
        try:
            with open(LOCAL_CONFIG, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            DEVICE_CODE = cfg.get('device_code')
            MY_STATION_ID = int(cfg.get('station_id', 0))
            mqtt_cfg = cfg.get('config', {}).get('mqtt') or cfg.get('mqtt') or {}
            if mqtt_cfg.get('broker'): MQTT_BROKER = mqtt_cfg.get('broker')
            if mqtt_cfg.get('port'): MQTT_PORT = int(mqtt_cfg.get('port'))
            if mqtt_cfg.get('username'): MQTT_USERNAME = mqtt_cfg.get('username')
            if mqtt_cfg.get('password'): MQTT_PASSWORD = mqtt_cfg.get('password')
        except Exception as e:
            logger.warning(f"Could not read local config: {e}")

# =====================================================
# MQTT CLIENT
# =====================================================
class MQTTPointClient:
    def __init__(self, broker, port, station_id, username="", password="", device_serial=""):
        self.broker = broker
        self.port = port
        self.station_id = station_id
        self.username = username
        self.password = password
        
        self.topic_alert = f"landslide/{station_id}/alert"
        self.topic_command = f"landslide/{station_id}/command"
        self.topic_pi_command = f"landslide/pi/{device_serial}/command" if device_serial else None
        
        self.is_locked = False
        self._load_lock_state()
        
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, client_id=f"pi-point-{device_serial}")
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect
        
        if username and password:
            self.client.username_pw_set(username, password)
    
    def connect(self):
        try:
            logger.info(f"🔌 MQTT Connect: {self.broker}:{self.port}")
            self.client.connect(self.broker, self.port, keepalive=60)
            self.client.loop_start()
            return True
        except Exception as e:
            logger.error(f"❌ Connect failed: {e}")
            return False
            
    def disconnect(self):
        self.client.loop_stop()
        self.client.disconnect()
        
    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            logger.info("✅ MQTT Connected, subscribing topics:")
            client.subscribe(self.topic_alert)
            client.subscribe(self.topic_command)
            logger.info(f"   - {self.topic_alert}")
            logger.info(f"   - {self.topic_command}")
            if self.topic_pi_command:
                client.subscribe(self.topic_pi_command)
                logger.info(f"   - {self.topic_pi_command}")
        else:
            logger.error(f"❌ Connection failed: {rc}")

    def _on_message(self, client, userdata, msg):
        try:
            payload = msg.payload.decode('utf-8', errors='ignore')
            logger.info(f"📡 MQTT [{msg.topic}]: {payload}")
            
            if msg.topic == self.topic_alert:
                self._handle_alert(payload)
            elif msg.topic == self.topic_command or (self.topic_pi_command and msg.topic == self.topic_pi_command):
                self._handle_command(payload)
        except Exception as e:
            logger.error(f"Error handling message: {e}")

    def _handle_alert(self, payload):
        global is_continuous_alert
        try:
            data = json.loads(payload)
            level = data.get('level', 'INFO').upper()
            
            audio_code = data.get('audio_code', '')
            category = data.get('category', '')

            # Kích hoạt GPIO nếu nhận lệnh cảnh báo nguy hiểm
            if level in ('WARNING', 'DANGER', 'CRITICAL'):
                if self.is_locked:
                    logger.warning("🔒 Locked. Ignore alert.")
                    return
                
                # Check if this is an IMU alert (requires continuous GPIO)
                if audio_code.startswith('imu_') or 'tilt' in category or 'shock' in category:
                    logger.info("🚨 IMU Alert received! Triggering continuous siren.")
                    is_continuous_alert = True
                    light_on()
                else:
                    logger.info("🚨 Standard Alert received. Triggering 15s GPIO pulse.")
                    threading.Thread(target=light_pulse, args=(15,), daemon=True).start()
        except Exception:
            pass

    def _handle_command(self, payload):
        global is_continuous_alert
        try:
            if payload.startswith('{'):
                data = json.loads(payload)
                cmd = data.get('cmd', data.get('action', ''))
                
                if cmd == 'install_license':
                    threading.Thread(target=self._handle_install_license, args=(data,), daemon=True).start()
                    return
                elif cmd == 'set_station':
                    self._handle_set_station(data)
                    return
                elif cmd == 'reset' or cmd == 'stop_siren':
                    is_continuous_alert = False
                    light_off()
                    if cmd == 'reset':
                        self._handle_reset()
                    return
                elif cmd == 'lock':
                    self.is_locked = True
                    self._save_lock_state(True)
                    return
                elif cmd == 'unlock':
                    self.is_locked = False
                    self._save_lock_state(False)
                    return
                elif cmd == 'on':
                    light_on()
                elif cmd == 'off':
                    light_off()
                
                # Kích hoạt GPIO nếu payload có level nguy hiểm (từ command topic)
                level = data.get('level', '').upper()
                audio_code = data.get('audio_code', '')
                category = data.get('category', '')
                
                if level in ('WARNING', 'DANGER', 'CRITICAL'):
                    if self.is_locked:
                        logger.warning("🔒 Locked. Ignore alert from command.")
                        return
                    
                    if audio_code.startswith('imu_') or 'tilt' in category or 'shock' in category:
                        logger.info(f"🚨 IMU Alert level={level} on command topic → activating continuous GPIO")
                        is_continuous_alert = True
                        light_on()
                    else:
                        logger.info(f"🚨 Alert level={level} on command topic → activating GPIO pulse")
                        threading.Thread(target=light_pulse, args=(15,), daemon=True).start()
                    
            else:
                # payload thô
                cmd = payload.strip().lower()
                if cmd == 'on': light_on()
                if cmd == 'off': light_off()
                if cmd == 'stop_siren' or cmd == 'reset':
                    is_continuous_alert = False
                    light_off()
        except:
            pass

    def _handle_install_license(self, data):
        try:
            license_str = data.get('license')
            local_code = DEVICE_CODE
            
            pi_base = generate_pi_license_base(local_code)
            cust_base = data.get('customer_base') or generate_customer_license_base()
            expected = get_license_code_from_string(pi_base + cust_base)
            
            if expected == (license_str or ''):
                logger.info(f"✅ License verified for Point {local_code}")
                # Confirm back to server
                try:
                    import requests
                    requests.post(f"{BACKEND_URL}/api/field/pi-devices/{data.get('device_id')}/confirm", 
                        json={"activated": True, "serial": local_code}, timeout=5)
                except: pass
            else:
                logger.warning("❌ License mismatch")
        except Exception as e:
            logger.error(e)

    def _handle_set_station(self, data):
        new_station = data.get('station_id')
        if not new_station: return
        try:
            cfg = {}
            if LOCAL_CONFIG.exists():
                with open(LOCAL_CONFIG, 'r', encoding='utf-8') as f: cfg = json.load(f)
            cfg['station_id'] = new_station
            with open(LOCAL_CONFIG, 'w', encoding='utf-8') as f: json.dump(cfg, f, indent=2)
            
            old_s = self.station_id
            self.station_id = new_station
            self.topic_alert = f"landslide/{new_station}/alert"
            self.topic_command = f"landslide/{new_station}/command"
            
            self.client.unsubscribe(f"landslide/{old_s}/alert")
            self.client.unsubscribe(f"landslide/{old_s}/command")
            self.client.subscribe(self.topic_alert)
            self.client.subscribe(self.topic_command)
            logger.info(f"🔄 Point moved to station {new_station}")
        except: pass

    def _handle_reset(self):
        if LOCAL_CONFIG.exists(): LOCAL_CONFIG.unlink()
        global MY_STATION_ID; MY_STATION_ID = 0
        self._handle_set_station({'station_id': 0})
        logger.info("✅ Reset complete.")

    def _save_lock_state(self, locked):
        try:
            cfg = {}
            if LOCAL_CONFIG.exists():
                with open(LOCAL_CONFIG, 'r') as f: cfg = json.load(f)
            cfg['is_locked'] = locked
            with open(LOCAL_CONFIG, 'w') as f: json.dump(cfg, f)
        except: pass

    def _load_lock_state(self):
        try:
            if LOCAL_CONFIG.exists():
                with open(LOCAL_CONFIG, 'r') as f:
                    self.is_locked = json.load(f).get('is_locked', False)
        except: pass
        
    def _on_disconnect(self, client, userdata, rc):
        pass

# =====================================================
# MAIN
# =====================================================
def main():
    logger.info("=========================================")
    logger.info("⚡ Pi Point (Field Station) - Lights/Siren")
    logger.info("=========================================")
    
    gpio_setup()
    auto_register_device()
    load_local_config()
    
    logger.info(f"📍 Station ID: {MY_STATION_ID}")
    
    client = MQTTPointClient(
        broker=MQTT_BROKER,
        port=MQTT_PORT,
        station_id=MY_STATION_ID,
        username=MQTT_USERNAME,
        password=MQTT_PASSWORD,
        device_serial=DEVICE_CODE
    )
    
    client.connect()
    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        client.disconnect()
        gpio_cleanup()
        
if __name__ == "__main__":
    main()
