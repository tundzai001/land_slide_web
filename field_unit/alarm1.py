#!/usr/bin/env python3

import RPi.GPIO as GPIO
import signal
import sys
import logging
import json
import paho.mqtt.client as mqtt

LIGHT_PIN = 17  # GPIO 17 (physical pin 11)

ACTIVE_HIGH = True

# MQTT config
MQTT_BROKER = "aitogy.asia"
MQTT_PORT = 1883
MQTT_TOPIC_CONTROL = "imu/light_control"
MQTT_TOPIC_STATUS = "imu/light_status"
MQTT_USERNAME = "mqttUser"
MQTT_PASSWORD = "MqttPassword123$%^"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

def gpio_setup():
    """Initialize GPIO pin."""
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    GPIO.setup(LIGHT_PIN, GPIO.OUT)
    # Start with light off
    GPIO.output(LIGHT_PIN, GPIO.LOW if ACTIVE_HIGH else GPIO.HIGH)
    logger.info(f"GPIO {LIGHT_PIN} initialized (active_high={ACTIVE_HIGH})")


def light_on():
    """Turn light on."""
    level = GPIO.HIGH if ACTIVE_HIGH else GPIO.LOW
    GPIO.output(LIGHT_PIN, level)
    logger.info(f"Light ON (GPIO {LIGHT_PIN})")


def light_off():
    """Turn light off."""
    level = GPIO.LOW if ACTIVE_HIGH else GPIO.HIGH
    GPIO.output(LIGHT_PIN, level)
    logger.info(f"Light OFF (GPIO {LIGHT_PIN})")


def get_light_status():
    """Return current light state as string 'ON' or 'OFF'."""
    current = GPIO.input(LIGHT_PIN)
    if ACTIVE_HIGH:
        return "ON" if current == GPIO.HIGH else "OFF"
    else:
        return "ON" if current == GPIO.LOW else "OFF"


def gpio_cleanup():
    """Clean up GPIO on exit."""
    GPIO.output(LIGHT_PIN, GPIO.LOW if ACTIVE_HIGH else GPIO.HIGH)
    GPIO.cleanup()
    logger.info("GPIO cleaned up")


def on_connect(client, userdata, flags, rc):
    """Called when connected to MQTT broker."""
    if rc == 0:
        client.subscribe(MQTT_TOPIC_CONTROL)
        logger.info(f"Connected to MQTT broker, subscribed to: {MQTT_TOPIC_CONTROL}")
    else:
        logger.error(f"MQTT connection failed, return code: {rc}")


def on_message(client, userdata, msg):
    """

      {"action": "on"}    - turn light on
      {"action": "off"}   - turn light off
      {"action": "status"} - publish current status
    """
    try:
        payload = json.loads(msg.payload.decode())
        action = payload.get("action", "").lower()

        logger.info(f"MQTT message received: {payload}")

        if action == "on":
            light_on()
        elif action == "off":
            light_off()
        elif action == "status":
            pass  # status is published below
        else:
            logger.warning(f"Unknown action: {action}")
            return

        # Publish status after every command
        status = get_light_status()
        client.publish(MQTT_TOPIC_STATUS, json.dumps({"status": status}))

    except json.JSONDecodeError:
        logger.error(f"Invalid JSON payload: {msg.payload}")
    except Exception as e:
        logger.error(f"Error handling MQTT message: {e}")

def main():
    """Main entry point. Sets up GPIO and MQTT, then waits for commands."""
    gpio_setup()

    mqtt_client = mqtt.Client()
    mqtt_client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message

    def signal_handler(sig, frame):
        logger.info("Shutting down...")
        mqtt_client.loop_stop()
        mqtt_client.disconnect()
        gpio_cleanup()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
        logger.info(f"Connecting to MQTT broker: {MQTT_BROKER}:{MQTT_PORT}")
        logger.info("Waiting for MQTT commands...")
        mqtt_client.loop_forever()
    except Exception as e:
        logger.error(f"Could not connect to MQTT broker: {e}")
    finally:
        gpio_cleanup()


if __name__ == "__main__":
    main()
