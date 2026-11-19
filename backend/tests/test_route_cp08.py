import os
import paho.mqtt.client as mqtt
import json

BROKER = os.getenv("MQTT_BROKER", "aitogy.asia")
PORT = int(os.getenv("MQTT_PORT", "1883"))
USER = os.getenv("MQTT_USER", "")
PASS = os.getenv("MQTT_PASSWORD", "")

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print("Connected to MQTT Broker!")
        topic = "command/ntrip/route/start"
        payload = {
            "station_code": "CP08",
            "host": "aitogy.click",
            "port": 2101,
            "mountpoint": "QN.CP",
            "password": "12345" # Bạn có thể đổi lại nếu caster yêu cầu mật khẩu khác
        }
        client.publish(topic, json.dumps(payload))
        print(f"Published to {topic}: {payload}")
        client.disconnect()
    else:
        print(f"Failed to connect, return code {rc}")

def main():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.username_pw_set(USER, PASS)
    client.on_connect = on_connect

    print(f"Connecting to {BROKER}:{PORT}...")
    client.connect(BROKER, PORT, 60)
    client.loop_forever()


if __name__ == "__main__":
    main()
