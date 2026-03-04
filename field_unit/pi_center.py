#pi_audio_player.py
import json
import logging
import time
import subprocess
import threading
import sys
import os
from pathlib import Path
from typing import Optional

# =====================================================
# IMPORTS
# =====================================================
try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("❌ paho-mqtt not installed. Run: pip install paho-mqtt")
    sys.exit(1)

try:
    import websocket
except ImportError:
    print("⚠️  websocket-client not installed (optional fallback)")
    websocket = None

# =====================================================
# CẤU HÌNH
# =====================================================
# MQTT (CHÍNH)
MQTT_BROKER = "aitogy.asia"              #
MQTT_PORT = 1883                          
MQTT_USERNAME = "mqttUser"                       
MQTT_PASSWORD = "MqttPassword123$%^"                        

# WebSocket (PHỤ - Fallback)
WEBSOCKET_BACKEND = "wss://monitoring.aitogy.com/ws/updates"  
# Station Config
MY_STATION_ID = 1                         
AUDIO_DIR = Path(__file__).parent / "landslide_audio"  # Cùng thư mục với script
LOCAL_CONFIG = Path.home() / ".landslide_device.json"

# Backend registration (for initial setup)
# Set BACKEND_URL env var to override (e.g. for local testing)
BACKEND_URL = os.getenv('BACKEND_URL', 'https://monitoring.aitogy.com')  

# Runtime values (may be overridden by local config)
DEVICE_CODE = None
MY_STATION_ID = MY_STATION_ID

# =====================================================
# LOGGING
# =====================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - PI_AUDIO - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# =====================================================
# AUDIO PLAYER
# =====================================================
class AudioPlayer:
    def __init__(self, audio_dir: Path):
        self.audio_dir = Path(audio_dir)
        self.current_audio_process = None
        self._last_siren_time = 0  # cooldown: tránh restart siren liên tục
        
        if not self.audio_dir.exists():
            logger.warning(f"🎵 Audio directory not found: {self.audio_dir}")
            logger.info(f"   Create it: mkdir -p {self.audio_dir}")
    
    def play(self, audio_code: str):
        """Phát siren khi nhận cảnh báo — luôn phát siren.mp3"""
        if not audio_code:
            logger.warning("⚠️ audio_code is empty")
            return
        
        # Pi Trung tâm chỉ kêu siren, không phát file theo audio_code
        audio_file = self.audio_dir / "siren.mp3"
        
        if not audio_file.exists():
            logger.error(f"❌ Siren file not found: {audio_file}")
            logger.info(f"   Hãy đặt file siren.mp3 vào: {self.audio_dir}")
            return
        
        # Nếu siren đang phát thì bỏ qua, đợi hết file rồi phát lại
        if self.current_audio_process and self.current_audio_process.poll() is None:
            return
        
        logger.info(f"🔊 Playing siren (triggered by: {audio_code})")
        
        import platform
        if platform.system() == 'Windows':
            try:
                # Windows: dùng cmd /c start để phát qua default media player
                self.current_audio_process = subprocess.Popen(
                    ['cmd', '/c', 'start', '', '/B', str(audio_file)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    shell=False
                )
                logger.info("   ▶️ Playing via Windows default player")
                return
            except Exception as e:
                logger.error(f"❌ Windows playback failed: {e}")
                return
        
        # Linux / Raspberry Pi
        try:
            # Sử dụng mpg123 (nhẹ, tốt cho Raspberry Pi)
            self.current_audio_process = subprocess.Popen(
                ['mpg123', '-q', str(audio_file)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        except FileNotFoundError:
            # Fallback 1: thử paplay (PulseAudio)
            try:
                logger.info("   mpg123 not found, trying paplay...")
                self.current_audio_process = subprocess.Popen(
                    ['paplay', str(audio_file)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            except FileNotFoundError:
                # Fallback 2: thử aplay (ALSA)
                try:
                    logger.info("   paplay not found, trying aplay...")
                    self.current_audio_process = subprocess.Popen(
                        ['aplay', str(audio_file)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
                except FileNotFoundError:
                    logger.error("   ❌ No audio player found (mpg123/paplay/aplay).")
                    logger.error("      Install: sudo apt-get install mpg123 alsa-utils")
    
    def _stop_current(self):
        """Dừng âm thanh đang phát"""
        if self.current_audio_process and self.current_audio_process.poll() is None:
            logger.info("   ⏹️  Stopping current audio")
            self.current_audio_process.terminate()
            try:
                self.current_audio_process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.current_audio_process.kill()
            self.current_audio_process = None


# -------------------------
# LICENSE UTILITIES (mirror backend)
# -------------------------
def get_license_code_from_string(string_number: str) -> str:
    try:
        import math
        length = len(string_number)
        if length == 0:
            return ""
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
    if len(base_code_str) > 12:
        return base_code_str[:12]
    else:
        return base_code_str.ljust(12, '0')


def generate_customer_license_base(identifier: str = "CUSTOMER") -> str:
    """Convert identifier to all-numeric base (same approach as pi_base) so
    the combined string can be passed to get_license_code_from_string as a float."""
    base_code_str = ""
    for char in identifier.upper():
        base_code_str += str(ord(char))
    if len(base_code_str) > 12:
        return base_code_str[:12]
    return base_code_str.ljust(12, '0')


def auto_register_device():
    """Register/heartbeat this device with backend on every startup.
    - First run: creates pi_devices record (status=pending)
    - Subsequent runs: updates last_seen, returns existing status + station_id
    """
    try:
        import requests
    except ImportError:
        logger.warning("⚠️ requests module not available - skipping register. Install: pip install requests")
        return

    try:
        # Load existing config to get serial/device_id if already registered
        existing_cfg = {}
        if LOCAL_CONFIG.exists():
            try:
                with open(LOCAL_CONFIG, 'r', encoding='utf-8') as f:
                    existing_cfg = json.load(f)
            except Exception:
                pass

        import sys
        prefix = "win" if sys.platform.startswith("win") else "pi"
        
        serial = (existing_cfg.get('device_code')
                  or DEVICE_CODE
                  or os.getenv('DEVICE_CODE')
                  or f"{prefix}-{int(time.time())}")
                  
        name_prefix = "Win" if prefix == "win" else "Pi"
        device_name = os.getenv('DEVICE_NAME', f'{name_prefix}-{serial[-8:]}')

        url = f"{BACKEND_URL}/api/field/register"
        # Use new schema: field "serial" (matches new PiDevice model)
        payload = {'serial': serial, 'name': device_name, 'device_type': prefix}

        logger.info(f"📡 Registering/heartbeat to {url} (serial={serial})")
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()

        result = resp.json()
        device_id   = result.get('device_id')
        status      = result.get('status', 'pending')
        station_id  = result.get('station_id') or existing_cfg.get('station_id', 0)

        logger.info(f"✅ Registration OK: device_id={device_id}, status={status}, station_id={station_id}")

        # Update local config with fresh data from backend
        cfg = {
            **existing_cfg,           # preserve any extra keys (license, mqtt overrides, etc.)
            'device_code': serial,
            'device_id':   device_id,
            'station_id':  station_id or 0,
        }
        with open(LOCAL_CONFIG, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        try:
            os.chmod(str(LOCAL_CONFIG), 0o600)
        except Exception:
            pass

        if status == 'pending':
            logger.info("   ⏳ Waiting for admin to activate this device...")
        elif status in ('activated', 'assigned'):
            logger.info(f"   ✅ Device is {status}, station_id={station_id}")

    except Exception as e:
        logger.warning(f"⚠️ Register/heartbeat failed: {e}")


def load_local_config():
    global DEVICE_CODE, MY_STATION_ID, MQTT_BROKER, MQTT_PORT, MQTT_USERNAME, MQTT_PASSWORD, WEBSOCKET_BACKEND
    if LOCAL_CONFIG.exists():
        try:
            with open(LOCAL_CONFIG, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            DEVICE_CODE = cfg.get('device_code') or cfg.get('device_id') or DEVICE_CODE
            MY_STATION_ID = int(cfg.get('station_id', MY_STATION_ID))
            mqtt = cfg.get('config', {}).get('mqtt') or cfg.get('mqtt') or {}
            if mqtt.get('broker'):
                MQTT_BROKER = mqtt.get('broker')
            if mqtt.get('port'):
                MQTT_PORT = int(mqtt.get('port'))
            if mqtt.get('username'):
                MQTT_USERNAME = mqtt.get('username')
            if mqtt.get('password'):
                MQTT_PASSWORD = mqtt.get('password')
            ws = cfg.get('config', {}).get('websocket') or cfg.get('websocket')
            if ws:
                WEBSOCKET_BACKEND = ws
            logger.info(f"Loaded local config: device_code={DEVICE_CODE}, station_id={MY_STATION_ID}")
        except Exception as e:
            logger.warning(f"Could not read local config: {e}")


# =====================================================
# MQTT CLIENT (CHÍNH)
# =====================================================
class MQTTAudioClient:
    def __init__(
        self,
        broker: str,
        port: int,
        station_id: int,
        audio_player: AudioPlayer,
        username: str = "",
        password: str = "",
        device_serial: str = ""
    ):
        self.broker = broker
        self.port = port
        self.station_id = station_id
        self.audio_player = audio_player
        self.username = username
        self.password = password
        
        # MQTT Topics for station alerts
        self.topic_alert = f"landslide/{station_id}/alert"
        self.topic_command = f"landslide/{station_id}/command"
        # Per-device topic (used for activation before station is assigned)
        self.topic_pi_command = f"landslide/pi/{device_serial}/command" if device_serial else None
        self.is_locked = False  # Lock state: khi bị khóa, Pi từ chối phát audio
        self._load_lock_state()  # Restore saved lock state
        
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, client_id=f"pi-audio-{station_id}")
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect
        self.client.on_log = self._on_log
        
        # Set username/password if provided
        if username and password:
            self.client.username_pw_set(username, password)
    
    def connect(self):
        """Kết nối đến MQTT Broker"""
        try:
            logger.info(f"🔌 MQTT: Connecting to {self.broker}:{self.port}...")
            self.client.connect(self.broker, self.port, keepalive=60)
            self.client.loop_start()  # Start background loop
            logger.info("✅ MQTT loop started")
        except Exception as e:
            logger.error(f"❌ MQTT connection failed: {e}")
            return False
        return True
    
    def disconnect(self):
        """Ngắt kết nối MQTT"""
        try:
            self.client.loop_stop()
            self.client.disconnect()
            logger.info("🔌 MQTT disconnected")
        except Exception as e:
            logger.error(f"Error disconnecting MQTT: {e}")
    
    def _on_connect(self, client, userdata, flags, rc):
        """Callback khi kết nối thành công"""
        if rc == 0:
            logger.info(f"✅ MQTT Connected (code: {rc})")
            logger.info(f"   📍 Station ID: {self.station_id}")
            logger.info(f"   📢 Topics:")
            logger.info(f"      - {self.topic_alert}")
            logger.info(f"      - {self.topic_command}")
            
            # Subscribe to topics
            client.subscribe(self.topic_alert)
            client.subscribe(self.topic_command)
            if self.topic_pi_command:
                client.subscribe(self.topic_pi_command)
                logger.info(f"      - {self.topic_pi_command} (device command)")
            logger.info("✅ Subscribed to topics")
        else:
            logger.error(f"❌ MQTT connection failed with code: {rc}")
    
    def _on_message(self, client, userdata, msg):
        """Callback khi nhận tin nhắn"""
        try:
            payload = msg.payload.decode('utf-8', errors='ignore')
            logger.info(f"📡 MQTT Message [{msg.topic}]: {payload}")
            
            # Xử lý dựa trên topic
            if msg.topic == self.topic_alert:
                self._handle_alert(payload)
            elif msg.topic == self.topic_command or (self.topic_pi_command and msg.topic == self.topic_pi_command):
                self._handle_command(payload)
            
        except Exception as e:
            logger.error(f"❌ Error handling MQTT message: {e}")
    
    def _handle_alert(self, payload: str):
        """Xử lý cảnh báo từ MQTT — chỉ log, không phát audio (đã xử lý trong _handle_command)"""
        try:
            data = json.loads(payload)
            level = data.get('level', 'INFO')
            message = data.get('message', '')
            logger.warning(f"🚨 ALERT [{level}]: {message}")
            # Audio đã được xử lý trong _handle_command, không phát lại ở đây
        except json.JSONDecodeError as e:
            logger.error(f"❌ Invalid JSON in alert: {e}")
    
    def _handle_command(self, payload: str):
        """Xử lý lệnh trực tiếp từ MQTT"""
        try:
            # payload có thể là JSON hoặc plain text (audio_code)
            if payload.startswith('{'):
                data = json.loads(payload)
                # handle install_license command
                if data.get('cmd') == 'install_license':
                    threading.Thread(target=self._handle_install_license, args=(data,), daemon=True).start()
                    return
                # handle set_station command
                if data.get('cmd') == 'set_station':
                    threading.Thread(target=self._handle_set_station, args=(data,), daemon=True).start()
                    return
                # handle reset command
                if data.get('cmd') == 'reset':
                    threading.Thread(target=self._handle_reset, daemon=True).start()
                    return
                # handle lock/unlock command
                if data.get('cmd') == 'lock':
                    self.is_locked = True
                    self._save_lock_state(True)
                    logger.warning("🔒 Device LOCKED by admin")
                    return
                if data.get('cmd') == 'unlock':
                    self.is_locked = False
                    self._save_lock_state(False)
                    logger.info("🔓 Device UNLOCKED by admin")
                    return

                # Kích hoạt audio nếu payload có level nguy hiểm (từ command topic)
                level = data.get('level', '').upper()
                if level in ('WARNING', 'DANGER', 'CRITICAL'):
                    audio_code = data.get('audio_code', '')
                    if audio_code:
                        if self.is_locked:
                            logger.warning(f"🔒 Locked, ignoring alert audio: {audio_code}")
                            return
                        logger.info(f"🚨 Alert level={level} on command topic → playing {audio_code}")
                        threading.Thread(
                            target=self.audio_player.play,
                            args=(audio_code,),
                            daemon=True
                        ).start()
                    return

                audio_code = data.get('audio_code', '')
            else:
                # Plain text: coi là audio_code trực tiếp
                audio_code = payload.strip()

            if audio_code:
                if self.is_locked:
                    logger.warning(f"🔒 Device locked, ignoring audio command: {audio_code}")
                    return
                logger.info(f"🎵 Command: Play {audio_code}")
                threading.Thread(
                    target=self.audio_player.play,
                    args=(audio_code,),
                    daemon=True
                ).start()
        except json.JSONDecodeError as e:
            logger.error(f"❌ Invalid JSON in command: {e}")

    def _handle_install_license(self, data: dict):
        """Handle license installation command from admin/backend."""
        try:
            license_str = data.get('license')
            device_code = data.get('device_code')
            customer_base = data.get('customer_base')

            # Determine our device code
            local_code = DEVICE_CODE or device_code
            if not local_code:
                logger.error("No local device code available to verify license")
                return

            # compute expected
            logger.info(f"   [verify] compute pi_base for {local_code}...")
            pi_base = generate_pi_license_base(local_code)
            logger.info(f"   [verify] pi_base={pi_base}")

            logger.info(f"   [verify] compute cust_base for {customer_base}...")
            cust_base = customer_base or generate_customer_license_base('CUSTOMER')
            logger.info(f"   [verify] cust_base={cust_base}")

            combined = pi_base + cust_base
            logger.info(f"   [verify] combined={combined}")

            expected = get_license_code_from_string(combined)
            logger.info(f"   [verify] expected={expected}")

            ok = (expected == (license_str or ''))


            if ok:
                logger.info(f"✅ License verified for device {local_code}")
                # persist license locally
                try:
                    cfg = {}
                    if LOCAL_CONFIG.exists():
                        with open(LOCAL_CONFIG, 'r', encoding='utf-8') as f:
                            cfg = json.load(f)
                    cfg.setdefault('config', {})
                    cfg['config']['license'] = license_str
                    with open(LOCAL_CONFIG, 'w', encoding='utf-8') as f:
                        json.dump(cfg, f, ensure_ascii=False, indent=2)
                except Exception as e:
                    logger.warning(f"Could not persist license locally: {e}")

                # Notify backend via HTTP callback
                device_id = data.get('device_id')
                if device_id:
                    try:
                        import requests
                        resp = requests.post(
                            f"{BACKEND_URL}/api/field/pi-devices/{device_id}/confirm",
                            json={"activated": True, "serial": local_code},
                            timeout=10
                        )
                        logger.info(f"📡 Confirm sent: {resp.status_code}")
                    except Exception as e:
                        logger.warning(f"Could not send confirm to backend: {e}")

                # send ack via MQTT status topic
                try:
                    status_topic = f"landslide/{self.station_id}/status"
                    ack_payload = json.dumps({"type": "license_installed", "device_code": local_code, "ok": True})
                    self.client.publish(status_topic, ack_payload)
                except Exception as e:
                    logger.warning(f"Failed to publish license ack: {e}")

            else:
                logger.warning(f"❌ License mismatch: expected {expected} got {license_str}")
                device_id = data.get('device_id')
                if device_id:
                    try:
                        import requests
                        requests.post(
                            f"{BACKEND_URL}/api/field/pi-devices/{device_id}/confirm",
                            json={"activated": False, "serial": local_code},
                            timeout=10
                        )
                    except Exception:
                        pass
                try:
                    status_topic = f"landslide/{self.station_id}/status"
                    fail_payload = json.dumps({"type": "license_installed", "device_code": local_code, "ok": False})
                    self.client.publish(status_topic, fail_payload)
                except Exception:
                    pass

        except Exception as e:
            logger.error(f"Error handling install_license: {e}")

    def _handle_set_station(self, data: dict):
        """Handle set_station command from backend after Pi is assigned to a station."""
        try:
            new_station_id = data.get('station_id')
            if not new_station_id:
                logger.warning("set_station: missing station_id")
                return

            logger.info(f"📍 Received set_station → station_id={new_station_id}")

            # Update local config
            try:
                cfg = {}
                if LOCAL_CONFIG.exists():
                    with open(LOCAL_CONFIG, 'r', encoding='utf-8') as f:
                        cfg = json.load(f)
                cfg['station_id'] = new_station_id
                with open(LOCAL_CONFIG, 'w', encoding='utf-8') as f:
                    json.dump(cfg, f, ensure_ascii=False, indent=2)
                logger.info(f"✅ station_id saved to local config: {new_station_id}")
            except Exception as e:
                logger.warning(f"Could not update local config: {e}")

            # Update in-memory station_id and resubscribe topics
            old_station = self.station_id
            self.station_id = new_station_id
            self.topic_alert   = f"landslide/{new_station_id}/alert"
            self.topic_command = f"landslide/{new_station_id}/command"

            # Unsubscribe old topics
            self.client.unsubscribe(f"landslide/{old_station}/alert")
            self.client.unsubscribe(f"landslide/{old_station}/command")
            # Subscribe new topics
            self.client.subscribe(self.topic_alert)
            self.client.subscribe(self.topic_command)
            logger.info(f"🔄 Resubscribed to station {new_station_id} topics")

        except Exception as e:
            logger.error(f"Error handling set_station: {e}")

    def _handle_reset(self):
        """Handle reset command from admin: delete local config (license, station, etc.)."""
        try:
            logger.warning("🔄 RESET command received from admin!")

            # 1. Delete local config file (contains license + station_id)
            if LOCAL_CONFIG.exists():
                LOCAL_CONFIG.unlink()
                logger.info(f"🗑️ Deleted local config: {LOCAL_CONFIG}")
            else:
                logger.info("   No local config file to delete")

            # 2. Reset in-memory state
            global DEVICE_CODE, MY_STATION_ID
            DEVICE_CODE = None
            old_station = self.station_id
            self.station_id = 0
            self.topic_alert   = "landslide/0/alert"
            self.topic_command = "landslide/0/command"

            # 3. Resubscribe to generic topics
            self.client.unsubscribe(f"landslide/{old_station}/alert")
            self.client.unsubscribe(f"landslide/{old_station}/command")
            self.client.subscribe(self.topic_alert)
            self.client.subscribe(self.topic_command)

            logger.info("✅ Pi reset complete. Restart Pi to re-register.")

        except Exception as e:
            logger.error(f"Error handling reset: {e}")

    def _save_lock_state(self, locked: bool):
        """Persist lock state to local config."""
        try:
            cfg = {}
            if LOCAL_CONFIG.exists():
                with open(LOCAL_CONFIG, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
            cfg['is_locked'] = locked
            with open(LOCAL_CONFIG, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Could not save lock state: {e}")

    def _load_lock_state(self):
        """Load lock state from local config."""
        try:
            if LOCAL_CONFIG.exists():
                with open(LOCAL_CONFIG, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                self.is_locked = cfg.get('is_locked', False)
                if self.is_locked:
                    logger.warning("🔒 Device is LOCKED (from local config)")
        except Exception:
            pass
    
    def _on_disconnect(self, client, userdata, rc):
        """Callback khi ngắt kết nối"""
        if rc != 0:
            logger.warning(f"⚠️ MQTT disconnected unexpectedly (code: {rc})")
        else:
            logger.info("🔌 MQTT disconnected")
    
    def _on_log(self, client, userdata, level, buf):
        """Log MQTT messages"""
        # logger.debug(f"[MQTT] {buf}")
        pass

# =====================================================
# WEBSOCKET CLIENT (PHỤ - Fallback)
# =====================================================
class WebSocketAudioClient:
    def __init__(self, backend_url: str, station_id: int, audio_player: AudioPlayer):
        self.backend_url = backend_url
        self.station_id = station_id
        self.audio_player = audio_player
        self.ws = None
        self.reconnect_delay = 5
        self.running = False
    
    def start(self):
        """Bắt đầu kết nối WebSocket (Fallback)"""
        self.running = True
        while self.running:
            try:
                logger.info(f"🔌 WebSocket: Connecting to {self.backend_url}...")
                self.ws = websocket.WebSocketApp(
                    self.backend_url,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close
                )
                
                self.ws.run_forever(ping_interval=30, ping_timeout=10)
            except Exception as e:
                logger.error(f"❌ WebSocket error: {e}")
                if self.running:
                    logger.info(f"⏳ Reconnecting in {self.reconnect_delay}s...")
                    time.sleep(self.reconnect_delay)
    
    def stop(self):
        """Dừng WebSocket"""
        self.running = False
        if self.ws:
            self.ws.close()
    
    def _on_open(self, ws):
        """Kết nối thành công"""
        logger.info("✅ WebSocket connected (Fallback mode)")
        logger.info(f"   📍 Station ID: {self.station_id}")
    
    def _on_message(self, ws, message):
        """Nhận tin nhắn từ WebSocket"""
        try:
            data = json.loads(message)
            msg_type = data.get('type', 'unknown')
            
            if msg_type == 'alert':
                station_id = data.get('station_id')
                if station_id == self.station_id:
                    audio_code = data.get('audio_code', '')
                    level = data.get('level', 'INFO')
                    msg = data.get('message', '')
                    
                    logger.warning(f"🚨 ALERT [{level}]: {msg}")
                    
                    if audio_code:
                        logger.info(f"   🔊 Audio Code: {audio_code}")
                        threading.Thread(
                            target=self.audio_player.play,
                            args=(audio_code,),
                            daemon=True
                        ).start()
        except json.JSONDecodeError as e:
            logger.error(f"❌ WebSocket parse error: {e}")
        except Exception as e:
            logger.error(f"❌ WebSocket error: {e}")
    
    def _on_error(self, ws, error):
        """Lỗi kết nối"""
        logger.error(f"❌ WebSocket Error: {error}")
    
    def _on_close(self, ws, close_status_code, close_msg):
        """Kết nối đóng"""
        logger.warning("⚠️ WebSocket closed")

# =====================================================
# MAIN
# =====================================================
def main():
    logger.info("=" * 70)
    logger.info("🎵 Pi Audio Player - Field Unit (MQTT + WebSocket)")
    logger.info("=" * 70)
    
    # Auto-register on first run
    auto_register_device()
    
    # Load local config if available
    load_local_config()
    
    logger.info(f"📍 Station ID: {MY_STATION_ID}")
    logger.info(f"🎵 Audio Dir: {AUDIO_DIR}")
    logger.info("")
    logger.info("🔴 PRIMARY:   MQTT @ {0}:{1}".format(MQTT_BROKER, MQTT_PORT))
    logger.info(f"   Topics:")
    logger.info(f"      - landslide/{MY_STATION_ID}/alert")
    logger.info(f"      - landslide/{MY_STATION_ID}/command")
    logger.info(f"🟡 FALLBACK:  WebSocket @ {WEBSOCKET_BACKEND}")
    logger.info("=" * 70)
    
    # Kiểm tra thư mục audio
    if not AUDIO_DIR.exists():
        logger.error(f"❌ Audio directory not found: {AUDIO_DIR}")
        logger.error(f"   Create it: mkdir -p {AUDIO_DIR}")
        logger.error(f"   Copy MP3 files there: cp *.mp3 {AUDIO_DIR}/")
        sys.exit(1)
    
    # Kiểm tra file mp3
    mp3_files = list(AUDIO_DIR.glob("*.mp3"))
    if not mp3_files:
        logger.warning(f"⚠️ No MP3 files found in {AUDIO_DIR}")
    else:
        logger.info(f"✅ Found {len(mp3_files)} audio files")
    
    # Khởi tạo Audio Player
    audio_player = AudioPlayer(AUDIO_DIR)
    
    # ✅ CHÍNH: Kết nối MQTT
    mqtt_client = MQTTAudioClient(
        broker=MQTT_BROKER,
        port=MQTT_PORT,
        station_id=MY_STATION_ID,
        audio_player=audio_player,
        username=MQTT_USERNAME,
        password=MQTT_PASSWORD,
        device_serial=DEVICE_CODE or ""
    )
    
    # ✅ PHỤ: WebSocket Fallback (nếu có websocket library)
    ws_client = None
    ws_thread = None
    if websocket:
        ws_client = WebSocketAudioClient(WEBSOCKET_BACKEND, MY_STATION_ID, audio_player)
        ws_thread = threading.Thread(target=ws_client.start, daemon=True)
        ws_thread.start()
        logger.info("✅ WebSocket fallback thread started")
    else:
        logger.warning("⚠️ websocket-client not installed, fallback disabled")

    # ✅ Heartbeat: cập nhật last_seen định kỳ
    def _heartbeat_loop():
        while True:
            time.sleep(60)
            try:
                import requests as _req
                serial = DEVICE_CODE or ""
                if not serial:
                    continue
                import sys as _sys
                prefix = "win" if _sys.platform.startswith("win") else "pi"
                name = f"{'Win' if prefix == 'win' else 'Pi'}-{serial[-8:]}"
                _req.post(
                    f"{BACKEND_URL}/api/field/register",
                    json={"serial": serial, "name": name, "device_type": prefix},
                    timeout=10
                )
            except Exception:
                pass

    hb_thread = threading.Thread(target=_heartbeat_loop, daemon=True)
    hb_thread.start()
    logger.info("✅ Heartbeat thread started (60s interval)")
    
    try:
        # Kết nối MQTT (chính)
        if mqtt_client.connect():
            logger.info("\n🚀 System ready! Waiting for MQTT messages...")
            
            # Giữ chạy
            while True:
                time.sleep(1)
        else:
            logger.error("❌ Failed to connect to MQTT broker")
            sys.exit(1)
    
    except KeyboardInterrupt:
        logger.info("\n🛑 Stopped by user")
        mqtt_client.disconnect()
        if ws_client:
            ws_client.stop()
        sys.exit(0)
    
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        mqtt_client.disconnect()
        if ws_client:
            ws_client.stop()
        sys.exit(1)

if __name__ == "__main__":
    main()