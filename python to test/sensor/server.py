import socket
import threading
import queue
import paho.mqtt.client as mqtt
import logging
from datetime import datetime, timezone, timedelta
import json

PORT = 5656

MQTT_BROKER = "aitogy.asia"
MQTT_PORT = 1883
MQTT_TOPIC = "imu/imu_angle_data"
MQTT_USERNAME = "mqttUser"
MQTT_PASSWORD = ""

mqtt_client = mqtt.Client()

# Queue bất đồng bộ để publish MQTT không block luồng đọc dữ liệu
# maxsize=500: nếu đầy sẽ drop dữ liệu cũ nhất thay vì treo chương trình
mqtt_queue = queue.Queue(maxsize=500)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

# ─── MQTT Callbacks ────────────────────────────────────────────────────────────

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        logging.info("Successfully connected to MQTT Broker")
    else:
        logging.error(f"Failed to connect to MQTT Broker. Return code: {rc}")

def on_publish(client, userdata, mid):
    pass  # Callback bắt buộc, không cần xử lý thêm

def on_disconnect(client, userdata, rc):
    if rc != 0:
        logging.warning(f"Unexpected MQTT disconnect (rc={rc}), will auto-reconnect")

# ─── Data Processing ───────────────────────────────────────────────────────────

def process_data(data):
    device = "WT66"
    if device == data[:4]:
        val = data[14:]
        upval = val.split(',')
        if len(upval) == 14:
            logging.debug(f"Device ID: {data[:12]} | Temp: {upval[6]} | Battery: {upval[7]} | Status: {upval[8]}")

            status_decoded = upval[8]
            status = "unknown"
            if status_decoded == "0":
                status = "normal"
            elif status_decoded.startswith(("X+", "X-", "Y+", "Y-")):
                status = "alarm"

            try:
                dt = datetime.strptime(upval[12], "%Y/%m/%d %H:%M:%S")
                dt = dt.replace(tzinfo=timezone(timedelta(hours=7)))
                timestamp = int(dt.timestamp())
            except ValueError as e:
                logging.error(f"Invalid timestamp format '{upval[12]}': {e}")
                return

            message = {
                "angle_xyz": [upval[3], upval[4], upval[5]],
                "battery_voltage": upval[7],
                "status": status,
                "timestamp": timestamp,
                "upload_interval": upval[9]
            }

            # Đẩy vào queue, không publish trực tiếp (tránh block luồng đọc)
            try:
                mqtt_queue.put_nowait(message)
            except queue.Full:
                # Queue đầy: bỏ tin nhắn cũ nhất, chèn tin mới
                logging.warning("MQTT queue full – dropping oldest message")
                try:
                    mqtt_queue.get_nowait()
                    mqtt_queue.put_nowait(message)
                except queue.Empty:
                    pass

def publish_mqtt(message):
    try:
        result = mqtt_client.publish(MQTT_TOPIC, json.dumps(message), qos=0)
        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            logging.info(f"Published: {message}")
        else:
            logging.error(f"Failed to publish. Return code: {result.rc}")
    except Exception as e:
        logging.error(f"Failed to publish message: {e}")

def mqtt_publisher_worker():
    """Thread riêng biệt xử lý publish MQTT – không ảnh hưởng đến luồng nhận dữ liệu."""
    while True:
        try:
            message = mqtt_queue.get(timeout=1)
            if message is None:  # Tín hiệu dừng
                break
            publish_mqtt(message)
            mqtt_queue.task_done()
        except queue.Empty:
            continue
        except Exception as e:
            logging.error(f"MQTT publisher worker error: {e}")

# ─── MQTT Connection ───────────────────────────────────────────────────────────

def connect_mqtt():
    try:
        mqtt_client.on_connect = on_connect
        mqtt_client.on_publish = on_publish
        mqtt_client.on_disconnect = on_disconnect

        mqtt_client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

        # Tự động kết nối lại khi mất kết nối (1s → 30s backoff)
        mqtt_client.reconnect_delay_set(min_delay=1, max_delay=30)

        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
        mqtt_client.loop_start()

        logging.info(f"Connecting to MQTT Broker: {MQTT_BROKER}")
    except Exception as e:
        logging.error(f"Could not connect to MQTT Broker: {e}")
        return False
    return True

# ─── TCP Client Handler ────────────────────────────────────────────────────────

class ClientHandler(threading.Thread):
    def __init__(self, client_socket, client_address):
        super().__init__(daemon=True)
        self.client_socket = client_socket
        self.client_address = client_address

    def run(self):
        try:
            # TCP_NODELAY: tắt Nagle's algorithm – giảm delay 40–200ms cho gói nhỏ
            self.client_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            # Timeout 120s: tự động đóng kết nối zombie
            self.client_socket.settimeout(120)

            with self.client_socket:
                # buffering=1: line-buffered – đọc ngay khi có '\n', không chờ buffer đầy
                reader = self.client_socket.makefile('r', buffering=1)
                writer = self.client_socket.makefile('w', buffering=1)

                while True:
                    data = reader.readline()
                    if not data:
                        break

                    data = data.strip()
                    if not data:
                        continue

                    logging.debug(f"Received from {self.client_address}: {data}")

                    if data.startswith("WT"):
                        response = data[:12] + "Q0\r\n"
                        writer.write(response)
                        writer.flush()
                        process_data(data)

        except socket.timeout:
            logging.warning(f"Client {self.client_address} timed out (120s inactivity)")
        except Exception as e:
            logging.error(f"Client handling error ({self.client_address}): {e}")
        finally:
            logging.info(f"Client disconnected: {self.client_address}")

# ─── Main ──────────────────────────────────────────────────────────────────────

def main():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind(('', PORT))
        server_socket.listen(50)
        print(f"Server started on port {PORT}")

        if not connect_mqtt():
            print("Failed to connect to MQTT broker. Exiting...")
            return

        # Khởi động thread publish MQTT bất đồng bộ
        publisher_thread = threading.Thread(target=mqtt_publisher_worker, daemon=True)
        publisher_thread.start()

        try:
            while True:
                try:
                    client_socket, client_address = server_socket.accept()
                    print(f"Client connected: {client_address}")

                    handler = ClientHandler(client_socket, client_address)
                    handler.start()

                except Exception as e:
                    logging.error(f"Server error: {e}")
                    break
        finally:
            mqtt_queue.put(None)  # Báo hiệu dừng publisher thread
            mqtt_client.loop_stop()
            mqtt_client.disconnect()

if __name__ == "__main__":
    main()
