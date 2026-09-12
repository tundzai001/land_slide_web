"""Read one device upload topic; never publish commands."""
import argparse
import getpass
import json
import time
from pathlib import Path

import paho.mqtt.client as mqtt

topic = 'device/860549070374009/upload'
parser = argparse.ArgumentParser()
parser.add_argument('--duration', type=float, default=30.0, help='capture duration in seconds')
args = parser.parse_args()
records = []
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.username_pw_set('mqttUser', getpass.getpass('MQTT password: '))

def connected(client, userdata, flags, reason, properties):
    print('Connection:', reason, flush=True)
    if reason == 0:
        client.subscribe(topic)

def received(client, userdata, message):
    payload = message.payload.decode('utf-8', errors='replace')
    records.append({'received_at': time.time(), 'retained': message.retain, 'payload': payload})
    if len(records) <= 3:
        print(payload, flush=True)

client.on_connect = connected
client.on_message = received
client.connect('aitogy.asia', 1883, 30)
client.loop_start()
try:
    time.sleep(args.duration)
finally:
    client.disconnect()
    client.loop_stop()
    destination = Path('mqtt_device_capture.json')
    destination.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Messages:', len(records), 'Saved:', destination)
