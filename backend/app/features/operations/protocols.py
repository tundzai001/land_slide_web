"""Industrial acquisition profiles for field gateways which publish to MQTT."""
import math
import os
import socket
import struct
import subprocess
import time
from typing import Literal

from pydantic import BaseModel, Field, model_validator


def system_time_status():
    """Read OS clock status without changing its configuration or time."""
    if os.name != 'nt':
        return {'service': 'System NTP', 'available': False, 'output': 'Kiểm tra dịch vụ chrony/systemd-timesyncd trên máy chủ.'}
    try:
        result = subprocess.run(['w32tm', '/query', '/status'], capture_output=True, text=True,
                                errors='replace', timeout=5)
        return {'service': 'Windows Time', 'available': result.returncode == 0,
                'output': (result.stdout or result.stderr).strip()[:8000]}
    except (OSError, subprocess.TimeoutExpired):
        return {'service': 'Windows Time', 'available': False, 'output': 'Không đọc được trạng thái Windows Time.'}


class Point(BaseModel):
    field: str = Field(pattern=r'^[A-Za-z][A-Za-z0-9_]{0,63}$')
    address: int = Field(default=0, ge=0, le=65535)
    node_id: str = Field(default='', max_length=256)
    data_type: Literal['uint16', 'int16', 'uint32', 'int32', 'float32', 'float64'] = 'uint16'
    register_type: Literal['holding', 'input'] = 'holding'
    word_order: Literal['big', 'little'] = 'big'
    byte_order: Literal['big', 'little'] = 'big'
    scale: float = 1.0
    offset: float = 0.0

    @model_validator(mode='after')
    def valid_number(self):
        if not math.isfinite(self.scale) or not math.isfinite(self.offset):
            raise ValueError('Scale and offset must be finite')
        size = {'uint16': 1, 'int16': 1, 'uint32': 2, 'int32': 2, 'float32': 2, 'float64': 4}[self.data_type]
        if self.address + size > 65536:
            raise ValueError('Register range exceeds 65535')
        return self


class AcquisitionProfile(BaseModel):
    protocol: Literal['mqtt', 'modbus_tcp', 'modbus_rtu', 'opcua'] = 'mqtt'
    enabled: bool = False
    host: str = Field(default='', max_length=255, pattern=r'^[A-Za-z0-9.:-]*$')
    port: int = Field(default=502, ge=1, le=65535)
    serial_port: str = Field(default='', max_length=255)
    baudrate: int = Field(default=9600, ge=1200, le=115200)
    parity: Literal['N', 'E', 'O'] = 'N'
    stopbits: Literal[1, 2] = 1
    unit_id: int = Field(default=1, ge=1, le=247)
    endpoint: str = Field(default='', max_length=512)
    poll_seconds: float = Field(default=5, ge=1, le=86400)
    # Gateway local certificate paths, never browser-supplied credentials.
    security: str = Field(default='', max_length=1024)
    points: list[Point] = Field(default_factory=list, max_length=64)

    @model_validator(mode='after')
    def valid_profile(self):
        if self.protocol == 'mqtt':
            self.enabled = False
            return self
        if not self.points:
            raise ValueError('An industrial protocol requires at least one mapping point')
        if len({p.field for p in self.points}) != len(self.points):
            raise ValueError('Mapping fields must be unique')
        if self.protocol == 'modbus_tcp' and not self.host:
            raise ValueError('Modbus TCP requires a host on the field network')
        if self.protocol == 'modbus_rtu' and not self.serial_port:
            raise ValueError('Modbus RTU requires a serial port on the gateway')
        if self.protocol == 'opcua':
            if not self.endpoint.startswith('opc.tcp://') or '@' in self.endpoint:
                raise ValueError('OPC UA requires an opc.tcp:// endpoint without embedded credentials')
            if any(not p.node_id for p in self.points):
                raise ValueError('OPC UA requires node IDs for every point')
        return self


def ntp_probe(server):
    """Measure offset only; OS clock discipline is managed by chrony/system NTP."""
    epoch = 2208988800
    # Pools resolve to several peers; one unreachable peer must not fail the check.
    peers = socket.getaddrinfo(server, 123, type=socket.SOCK_DGRAM)
    last_error = TimeoutError('No NTP peer responded')
    for family, _, _, _, address in peers[:4]:
        sent = time.time()
        request = bytearray(48)
        request[0] = 0x23  # NTP v4, client mode
        struct.pack_into('!II', request, 40, int(sent) + epoch, int((sent % 1) * 2**32))
        try:
            with socket.socket(family, socket.SOCK_DGRAM) as client:
                client.settimeout(2)
                client.connect(address)
                client.send(request)
                packet = client.recv(512)
            break
        except OSError as exc:
            last_error = exc
    else:
        raise last_error
    received = time.time()
    if len(packet) < 48 or packet[0] & 7 != 4 or packet[0] >> 6 == 3 or not 1 <= packet[1] <= 15:
        raise ValueError('NTP server returned an unsynchronized or invalid response')
    if packet[24:32] != request[40:48]:
        raise ValueError('NTP originate timestamp mismatch')
    def stamp(index):
        whole, fraction = struct.unpack_from('!II', packet, index)
        return whole - epoch + fraction / 2**32
    t2, t3 = stamp(32), stamp(40)
    return {'server': server, 'checked_at': int(received), 'offset_ms': ((t2 - sent) + (t3 - received)) * 500,
            'round_trip_ms': ((received - sent) - (t3 - t2)) * 1000,
            'stratum': packet[1], 'clock_changed': False, 'mode': 'measurement_only'}
