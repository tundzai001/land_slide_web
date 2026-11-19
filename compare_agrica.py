import os
import paho.mqtt.client as mqtt
import re

MQTT_BROKER = os.getenv("MQTT_BROKER", "aitogy.asia")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME", os.getenv("MQTT_USER", ""))
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")

DEVICES = {
    os.getenv("DEVICE_TOPIC_1", "device/DAP1_1_DEMO/upload"): "Dap1_1",
    os.getenv("DEVICE_TOPIC_2", "device/DAP1_2_DEMO/upload"): "Dap1_2",
    os.getenv("DEVICE_TOPIC_3", "device/DAP1_3_DEMO/upload"): "Dap1_3",
    os.getenv("DEVICE_TOPIC_4", "device/DAP1_4_DEMO/upload"): "Dap1_4",
}

buffers = dict.fromkeys(DEVICES, "")

def parse_and_compare(device_name, sentence, is_truncated=False):
    # Analyze the sentence length and structure
    length = len(sentence)
    
    # Try to extract satellite counts from GNSS part
    # Format: ;GNSS,len,year,month,day,hour,min,sec,pos_type,head_status,GPS,BDS,GLO,GAL...
    parts = sentence.split(";")
    sat_info = "N/A"
    if len(parts) > 1:
        data_parts = parts[1].split(",")
        if data_parts[0] == "GNSS" and len(data_parts) > 14:
            gps = data_parts[11]
            bds = data_parts[12]
            glo = data_parts[13]
            try:
                # GAL might be at index 55 but let's just show the first three
                sat_info = f"GPS:{gps} BDS:{bds} GLO:{glo}"
            except IndexError:
                pass

    status = "TRUNCATED (Missing *)" if is_truncated else "COMPLETE (Has *)"
    
    # Check if the CRC is fully 8 chars if not truncated
    crc_part = ""
    if "*" in sentence:
        crc_part = sentence.split("*")[-1]
    
    print(f"[{device_name.ljust(6)}] {status.ljust(22)} | Length: {str(length).ljust(4)} | Sats: {sat_info.ljust(20)} | CRC received: '{crc_part}' | End of string: {sentence[-15:]}")


def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print(f"Connected to {MQTT_BROKER} successfully!")
        for topic in DEVICES:
            client.subscribe(topic)
            print(f"Subscribed to {topic} ({DEVICES[topic]})")
    else:
        print(f"Connection failed with code {rc}")

def on_message(client, userdata, msg):
    topic = msg.topic
    if topic not in DEVICES:
        return
        
    device_name = DEVICES[topic]
    payload = msg.payload.decode('utf-8', errors='ignore')
    
    # Check for new AGRICA header which would mean the previous buffer was truncated
    if "#AGRICA" in payload:
        idx = payload.find("#AGRICA")
        # If there's something in the buffer, it was truncated because a new header arrived!
        if buffers[topic]:
            # Print the truncated buffer
            parse_and_compare(device_name, buffers[topic], is_truncated=True)
        # Reset buffer to start from the new header
        buffers[topic] = payload[idx:]
    else:
        # Append chunk
        buffers[topic] += payload

    # Now check if the current buffer has a complete sentence (contains '*')
    if "*" in buffers[topic]:
        # Wait, if it has '*', it might still be receiving the CRC.
        # But we can just use the regex to extract it
        match = re.search(r'(#AGRICA[^*]*\*[0-9a-fA-F]*)', buffers[topic])
        if match:
            complete_sentence = match.group(1)
            parse_and_compare(device_name, complete_sentence, is_truncated=False)
            
            # Remove the processed sentence from buffer
            buffers[topic] = buffers[topic][match.end():]


client = mqtt.Client()
if MQTT_USERNAME and MQTT_PASSWORD:
    client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

client.on_connect = on_connect
client.on_message = on_message

print("Starting AGRICA Comparison tool...")
try:
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    client.loop_forever()
except KeyboardInterrupt:
    print("Stopped.")
