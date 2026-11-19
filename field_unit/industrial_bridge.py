"""Optional read-only Modbus/OPC UA gateway publishing existing sensor JSON to MQTT.

Usage: python field_unit/industrial_bridge.py --config gateway-device-7.json
Broker and OPC UA credentials are read only from gateway environment variables.
"""
import argparse
import asyncio
import json
import logging
import math
import os
import struct
import time
from pathlib import Path

logger = logging.getLogger('industrial_bridge')


def decode_registers(registers, point):
    code = {'uint16': 'H', 'int16': 'h', 'uint32': 'I', 'int32': 'i', 'float32': 'f', 'float64': 'd'}[point.get('data_type', 'uint16')]
    if len(registers) != struct.calcsize(code) // 2:
        raise ValueError('Incomplete register response')
    words = list(registers)
    if point.get('word_order', 'big') == 'little':
        words.reverse()
    raw = b''.join(int(word).to_bytes(2, point.get('byte_order', 'big')) for word in words)
    value = struct.unpack('>' + code, raw)[0] * point.get('scale', 1) + point.get('offset', 0)
    if not math.isfinite(value):
        raise ValueError('Non-finite sensor value')
    return value


async def read_modbus(profile):
    from pymodbus.client import AsyncModbusSerialClient, AsyncModbusTcpClient
    common = {'timeout': 3, 'retries': 1}
    if profile['protocol'] == 'modbus_tcp':
        client = AsyncModbusTcpClient(profile['host'], port=profile.get('port', 502), **common)
    else:
        client = AsyncModbusSerialClient(profile['serial_port'], baudrate=profile.get('baudrate', 9600),
                                        parity=profile.get('parity', 'N'), stopbits=profile.get('stopbits', 1), **common)
    try:
        if not await client.connect():
            raise ConnectionError('Modbus connection unavailable')
        payload = {}
        for point in profile['points']:
            count = {'uint16': 1, 'int16': 1, 'uint32': 2, 'int32': 2, 'float32': 2, 'float64': 4}[point.get('data_type', 'uint16')]
            read = client.read_input_registers if point.get('register_type') == 'input' else client.read_holding_registers
            response = await read(point.get('address', 0), count=count, device_id=profile.get('unit_id', 1))
            if response.isError():
                raise ValueError('Modbus exception response')
            payload[point['field']] = decode_registers(response.registers, point)
        return payload
    finally:
        client.close()


async def read_opcua(profile):
    from asyncua import Client
    client = Client(profile['endpoint'], timeout=3)
    if profile.get('security'):
        await client.set_security_string(profile['security'])
    elif os.environ.get('OPCUA_ALLOW_INSECURE') != '1':
        raise ValueError('Configure OPC UA security or explicitly allow an isolated insecure test server')
    if os.environ.get('OPCUA_USERNAME'):
        client.set_user(os.environ['OPCUA_USERNAME'])
        client.set_password(os.environ.get('OPCUA_PASSWORD', ''))
    async with client:
        payload = {}
        for point in profile['points']:
            # read_data_value validates the server's StatusCode before use.
            data = await client.get_node(point['node_id']).read_data_value()
            value = float(data.Value.Value) * point.get('scale', 1) + point.get('offset', 0)
            if not math.isfinite(value):
                raise ValueError('Non-finite OPC UA value')
            payload[point['field']] = value
        return payload


async def read_device(device):
    profile = device['profile']
    async with asyncio.timeout(30):
        payload = await (read_opcua(profile) if profile['protocol'] == 'opcua' else read_modbus(profile))
    required = {'water': {'water_level'}, 'rain': {'rainfall_mm'}, 'imu': {'roll', 'pitch', 'yaw'}}[device['sensor_type']]
    if not required.issubset(payload):
        raise ValueError(f'Missing sensor fields: {sorted(required - payload.keys())}')
    return payload


def _validate_gateway_config(config):
    if config.get('version') != 1:
        raise ValueError('Unsupported gateway configuration version')
    devices = [d for d in config.get('devices', []) if d['profile'].get('enabled') and d['profile']['protocol'] != 'mqtt']
    if not devices:
        raise ValueError('No enabled industrial profiles; existing MQTT devices require no bridge')
    for device in devices:
        if not device.get('topic') or any(char in device['topic'] for char in '+#\x00'):
            raise ValueError('A concrete MQTT publish topic is required')
        if device['sensor_type'] not in {'water', 'rain', 'imu'}:
            raise ValueError('Unsupported sensor type')
    return devices


def _setup_mqtt_client():
    import paho.mqtt.client as mqtt
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=os.environ.get('MQTT_CLIENT_ID', 'landslide-industrial-gateway')
    )
    client.max_queued_messages_set(100)
    if os.environ.get('MQTT_USERNAME'):
        client.username_pw_set(os.environ['MQTT_USERNAME'], os.environ.get('MQTT_PASSWORD'))
    if os.environ.get('MQTT_TLS_CA'):
        client.tls_set(ca_certs=os.environ['MQTT_TLS_CA'])
    client.connect_async(os.environ['MQTT_HOST'], int(os.environ.get('MQTT_PORT', '1883')))
    client.loop_start()
    return client


async def _poll_and_publish_device(client, device):
    identifier = device['device_id']
    try:
        payload = await read_device(device)
        info = client.publish(device['topic'], json.dumps(payload, allow_nan=False), qos=1, retain=False)
        await asyncio.to_thread(info.wait_for_publish, 5)
        if not info.is_published():
            raise ConnectionError('MQTT publish acknowledgement timed out')
        logger.info('Published device %s', identifier)
    except Exception as exc:
        logger.exception('Device %s read/publish failed: %s', identifier, type(exc).__name__)


async def run(config):
    devices = _validate_gateway_config(config)
    client = _setup_mqtt_client()
    next_read = {}
    disconnected_logged = False
    try:
        while True:
            if not client.is_connected():
                if not disconnected_logged:
                    logger.warning('MQTT unavailable; acquisition paused until the broker reconnects')
                    disconnected_logged = True
                await asyncio.sleep(1)
                continue
            disconnected_logged = False
            for device in devices:
                identifier = device['device_id']
                if time.monotonic() < next_read.get(identifier, 0):
                    continue
                await _poll_and_publish_device(client, device)
                next_read[identifier] = time.monotonic() + max(1, float(device['profile'].get('poll_seconds', 5)))
            await asyncio.sleep(0.2)
    finally:
        client.disconnect()
        client.loop_stop()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    try:
        asyncio.run(run(json.loads(Path(args.config).read_text(encoding='utf-8'))))
    except KeyboardInterrupt:
        pass
