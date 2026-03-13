import paho.mqtt.client as mqtt
import json
import time
import serial
from datetime import datetime, timedelta

mqtt_client = mqtt.Client()

class RainGaugeMonitor:
    def __init__(self):
        self.last_rain_value = None
        self.last_rain_timestamp = None
        self.total_rainfall = 0.0
        self.rain_data = []
        
    def calculate_delta_rain(self, current_value, current_timestamp):    
        if self.last_rain_value is None:
            self.last_rain_value = current_value
            self.last_rain_timestamp = current_timestamp
            return {
                'intensity_mmh': 0.0,
                'delta_rain': 0.0,
                'delta_time_seconds': 0.0,
                'status': 'initialized'
            }
        
        delta_rain = current_value - self.last_rain_value
        delta_time_seconds = current_timestamp - self.last_rain_timestamp
       
        status = 'no_rain'
        
        if delta_rain > 0 and delta_time_seconds > 0:
            self.total_rainfall += delta_rain
            status = 'raining'
        elif delta_rain < 0:
            status = 'reset_detected'
            delta_rain = 0
        else:
            if delta_time_seconds > 120:
                status = 'no_rain'
            intensity = 0.0
        
        result = {
            'intensity_mmh': 0.0,
            'delta_rain': round(delta_rain, 4),
            'delta_time_seconds': round(delta_time_seconds, 2),
            'status': status
        }
        

        self.last_rain_timestamp = current_timestamp
        self.last_rain_value = current_value
        
        return result
    
    def calculate_interval_rainfall(self):
        if not self.rain_data or len(self.rain_data) < 2:
            return None
        
        current_time = datetime.now()
        rainfall = {}
        

        minute_ago = current_time - timedelta(minutes=1)
        minute_rain = 0
        for data in reversed(self.rain_data):
            data_time = datetime.fromisoformat(data['timestamp_str'])
            if data_time >= minute_ago:
                minute_rain += data.get('delta_rain', 0)
            else:
                break
        rainfall['last_minute'] = round(minute_rain, 4)

        five_minute_ago = current_time - timedelta(minutes=5)
        five_minute_rain = 0
        for data in reversed(self.rain_data):
            data_time = datetime.fromisoformat(data['timestamp_str'])
            if data_time >= five_minute_ago:
                five_minute_rain += data.get('delta_rain', 0)
            else:
                break
        rainfall['last_5_minutes'] = round(five_minute_rain, 4)
        
        hour_ago = current_time - timedelta(hours=1)
        hour_rain = 0
        for data in reversed(self.rain_data):
            data_time = datetime.fromisoformat(data['timestamp_str'])
            if data_time >= hour_ago:
                hour_rain += data.get('delta_rain', 0)
            else:
                break
        rainfall['last_hour'] = round(hour_rain, 4)
        

        day_ago = current_time - timedelta(days=1)
        day_rain = 0
        for data in reversed(self.rain_data):
            data_time = datetime.fromisoformat(data['timestamp_str'])
            if data_time >= day_ago:
                day_rain += data.get('delta_rain', 0)
            else:
                break
        rainfall['last_24h'] = round(day_rain, 4)
        
        return rainfall

class MQTTRainClient:
    def __init__(self, broker_host, broker_port=1883, topic="device/+/upload", username=None, password=None):
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.topic = topic
        self.username = username
        self.password = password
        
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)
        self.rain_monitor = RainGaugeMonitor()
        
        # Set up callbacks
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.on_disconnect = self.on_disconnect
        
        # Set credentials if provided
        if username and password:
            self.client.username_pw_set(username, password)
    
    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            print(f"Connected to MQTT broker at {self.broker_host}:{self.broker_port}")
            client.subscribe(self.topic)
            print(f"Subscribed to topic: {self.topic}")
            print("Starting Rain Gauge monitoring...")
        else:
            print(f"Failed to connect to MQTT broker. Return code: {rc}")

    def publish_mqtt(self, message, topic='modbus_data_03'):
        try:
            self.client.publish(topic, message)
            print(f"Published message to MQTT: {message}")
        except Exception as e:
            print(f"Failed to publish message: {e}")

    def on_message(self, client, userdata, msg):
        try:
            message = msg.payload.decode('utf-8').strip()
            print(f"\nReceived message on {msg.topic}")
            
            # Parse JSON data
            data = json.loads(message)
            
            # Check if it's rain sensor data
            if data.get('sensortype') == 'RSB':
                self.process_rain_data(data)
            else:
                print(f"Skipping non-rain sensor data: {data.get('sensortype')}")
                
        except json.JSONDecodeError as e:
            print(f"Error parsing JSON: {e}")
        except Exception as e:
            print(f"Error processing message: {e}")
    
    def on_disconnect(self, client, userdata, rc):
        print(f"Disconnected from MQTT broker. Return code: {rc}")
    
    def process_rain_data(self, data):
        """Process rain gauge data and calculate intensity"""
        sensor_name = data.get('sensorname', 'Unknown')
        modbus_id = data.get('modbus_id', 'N/A')
        timestamp = data.get('timestamp')
        rain_value = data.get('value')
        sensor_status = data.get('status', 'Unknown')
        
        if rain_value is None or timestamp is None:
            print("Invalid data: missing value or timestamp")
            return
        
        # Calculate intensity
        intensity_data = self.rain_monitor.calculate_delta_rain(rain_value, timestamp)
        
        # Get interval rainfall
        interval_rainfall = self.rain_monitor.calculate_interval_rainfall()
   
        intensity_avg = 0.0

        if interval_rainfall:
            # Intensity (mm/h) = (total mm in 5 mins) / (5/60 hours)
            intensity_avg = interval_rainfall['last_5_minutes'] * 12
        
        # Display data
        timestamp_str = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')

        timestamp_str_2 = datetime.now().isoformat(timespec="seconds")


        data_to_publish = {
                    "sensortype": "RAIN",
                    "sensorname": "ATG_RAIN", 
                    "timestamp": timestamp_str_2,
                    "rainfall_mm": round(rain_value,2),
                    "intensity_mm_h": round(intensity_avg,2),
                    "status": "Normal" 
                }
        
        print("\n" + "="*60)
        print("RAIN GAUGE DATA:")
        print("="*60)
        print(f"Sensor Name: {sensor_name}")
        print(f"Modbus ID: {modbus_id}")
        print(f"Time: {timestamp_str}")
        print(f"Status: {sensor_status}")
        print(f"Current Value: {rain_value:.4f} mm")
        
        print("-" * 30)
        print("RAINFALL INTENSITY:")
        print(f"Delta Rain: {intensity_data['delta_rain']:.4f} mm")
        print(f"Status: {intensity_data['status']}")
        
        if interval_rainfall:
            print("-" * 30)
            print("ACCUMULATED RAINFALL:")
            print(f"Last 1 minute: {interval_rainfall['last_minute']:.4f} mm")
            print(f"Last 1 hour: {interval_rainfall['last_hour']:.4f} mm")
            print(f"Last 5 minutes: {interval_rainfall['last_5_minutes']:.4f} mm")
            print(f"Last 24 hours: {interval_rainfall['last_24h']:.4f} mm")
        self.publish_mqtt(json.dumps(data_to_publish))
        
        print("-" * 30)
        print(f"Total Rainfall (Session): {self.rain_monitor.total_rainfall:.4f} mm")
        print("="*60)
        
        rain_record = {
            'sensorname': sensor_name,
            'modbus_id': modbus_id,
            'timestamp': timestamp,
            'timestamp_str': timestamp_str,
            'rain_value_mm': rain_value,
            'sensor_status': sensor_status,
            'intensity_mmh': intensity_data['intensity_mmh'],
            'delta_rain': intensity_data['delta_rain'],
            'delta_time_seconds': intensity_data['delta_time_seconds'],
            'calculation_status': intensity_data['status'],
            'total_rainfall': self.rain_monitor.total_rainfall
        }
        
        self.rain_monitor.rain_data.append(rain_record)

        last_clear_date = None
        now = datetime.now()

        # Run the clear command once per day at 00:00:00
        if now.hour == 0 and now.minute == 0 and (last_clear_date != now.date()):
            self.clear_precipitation()
            last_clear_date = now.date()

        
    
    def save_to_file(self, data, filename="rain_data.json"):
        """Save data to JSON file"""
        try:
            with open(filename, 'a') as f:
                json.dump(data, f)
                f.write('\n')
        except Exception as e:
            print(f"Error saving to file: {e}")
    
    def get_summary(self):
        """Get summary of rain monitoring session"""
        if not self.rain_monitor.rain_data:
            return "No rain data available"
        
        summary = {
            'total_rainfall_mm': round(self.rain_monitor.total_rainfall, 4),
            'total_records': len(self.rain_monitor.rain_data),
            'start_time': self.rain_monitor.rain_data[0]['timestamp_str'] if self.rain_monitor.rain_data else None,
            'end_time': self.rain_monitor.rain_data[-1]['timestamp_str'] if self.rain_monitor.rain_data else None
        }
        
        if len(self.rain_monitor.rain_data) > 1:
            start_ts = self.rain_monitor.rain_data[0]['timestamp']
            end_ts = self.rain_monitor.rain_data[-1]['timestamp']
            duration_seconds = end_ts - start_ts
            
            summary['duration_hours'] = round(duration_seconds / 3600, 2)
            summary['average_intensity_mmh'] = round(
                self.rain_monitor.total_rainfall / (duration_seconds / 3600), 4
            ) if duration_seconds > 0 else 0
        
        return summary
    
    def start(self):
        """Start the MQTT client"""
        try:
            print(f"Connecting to MQTT broker at {self.broker_host}:{self.broker_port}...")
            self.client.connect(self.broker_host, self.broker_port, 60)
            self.client.loop_forever()
        except Exception as e:
            print(f"Error starting MQTT client: {e}")
    
    def stop(self):
        """Stop the MQTT client and show summary"""
        summary = self.get_summary()
        if isinstance(summary, dict):
            print(f"Total Rainfall: {summary['total_rainfall_mm']} mm")
            print(f"Total Records: {summary['total_records']}")
            if 'duration_hours' in summary:
                print(f"Duration: {summary['duration_hours']} hours")
                print(f"Average Intensity: {summary['average_intensity_mmh']} mm/h")
            print(f"Start Time: {summary['start_time']}")
            print(f"End Time: {summary['end_time']}")
        else:
            print(summary)
        print("="*60)
        
        self.client.disconnect()

    def clear_precipitation():
        port = '/dev/sensor2'
        baudrate = 4800

        frame = bytes.fromhex('01 06 00 00 00 5A 09 F1')
        ser = serial.Serial(port, baudrate=baudrate, bytesize=8, parity='N', stopbits=1, timeout=1)
        try:
            # Send command
            print("Sending clear precipitation command...")
            ser.write(frame)
            time.sleep(0.1)

            # Read response (should be identical)
            reply = ser.read(8)
            if reply:
                print("Response:", reply.hex(' ').upper())
                if reply == frame:
                    print("Precipitation cleared successfully.")
                else:
                    print("Received unexpected response check wiring or CRC.")
            else:
                print("No response. Check RS485 wiring or address.")
        finally:
            ser.close()


def main():
    BROKER_HOST = "aitogy.asia"
    BROKER_PORT = 1883
    TOPIC = "modbus_data_02"
    USERNAME = "mqttUser"
    PASSWORD = ""

    # Create and start MQTT client
    client = MQTTRainClient(
        broker_host=BROKER_HOST,
        broker_port=BROKER_PORT,
        topic=TOPIC,
        username=USERNAME,
        password=PASSWORD
    )
    
    try:
        print("Starting MQTT Rain Gauge Monitor...")
        print("Press Ctrl+C to stop")
        client.start()
    except KeyboardInterrupt:
        print("Shutting down...")
        client.stop()

if __name__ == "__main__":
    main()
