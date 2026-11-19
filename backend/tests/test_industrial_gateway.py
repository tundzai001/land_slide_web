"""Read real local protocol simulators through the production gateway drivers."""
import asyncio
import importlib.util
import math
import os
from pathlib import Path
import select
import socket
import struct
import tty

import pytest

spec = importlib.util.spec_from_file_location('industrial_bridge', Path(__file__).resolve().parents[2] / 'field_unit' / 'industrial_bridge.py')
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


def test_decode_register_types_and_word_order():
    registers = list(struct.unpack('>HH', struct.pack('>f', 12.5)))
    assert bridge.decode_registers(registers, {'data_type':'float32'}) == 12.5
    assert bridge.decode_registers(registers[::-1], {'data_type':'float32','word_order':'little','scale':2,'offset':1}) == 26
    assert bridge.decode_registers([65535], {'data_type':'int16'}) == -1
    with pytest.raises(ValueError):
        bridge.decode_registers([0], {'data_type':'float32'})
    with pytest.raises(ValueError):
        bridge.decode_registers([0x7fc0,0], {'data_type':'float32'})


def test_modbus_tcp_real_socket():
    async def run():
        async def respond(reader, writer):
            try:
                packet = await reader.readexactly(12)
                transaction, protocol, length, unit, function, address, count = struct.unpack('>HHHBBHH', packet)
                assert (protocol, length, unit, function, address, count) == (0,6,1,3,0,2)
                data = struct.pack('>f', 12.5)
                writer.write(struct.pack('>HHHBBB', transaction,0,7,unit,function,4) + data)
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()
        async with await asyncio.start_server(respond, '127.0.0.1', 0) as server:
            port = server.sockets[0].getsockname()[1]
            payload = await bridge.read_device({'sensor_type':'water','profile':{'protocol':'modbus_tcp','host':'127.0.0.1','port':port,'points':[{'field':'water_level','address':0,'data_type':'float32'}]}})
            assert payload == {'water_level':12.5}
    asyncio.run(run())


def _calc_modbus_crc(data):
    value = 0xffff
    for byte in data:
        value ^= byte
        for _ in range(8):
            value = (value >> 1) ^ 0xa001 if value & 1 else value >> 1
    return value.to_bytes(2, 'little')


def _handle_pty_respond(master):
    packet = b''
    while len(packet) < 8:
        if not select.select([master], [], [], 5)[0]:
            raise TimeoutError('RTU simulator received no request')
        packet += os.read(master, 8 - len(packet))
    assert packet[-2:] == _calc_modbus_crc(packet[:-2])
    data = b'\x01\x03\x04' + struct.pack('>f', 3.5)
    os.write(master, data + _calc_modbus_crc(data))


def test_modbus_rtu_real_serial_pty():
    async def run():
        master, slave = os.openpty()
        tty.setraw(slave)
        try:
            task = asyncio.create_task(asyncio.to_thread(_handle_pty_respond, master))
            value = await bridge.read_device({'sensor_type':'water','profile':{'protocol':'modbus_rtu','serial_port':os.ttyname(slave),'points':[{'field':'water_level','address':0,'data_type':'float32'}]}})
            await task
            assert value == {'water_level':3.5}
        finally:
            os.close(master)
            os.close(slave)
    asyncio.run(run())


def test_opcua_real_local_server(monkeypatch):
    monkeypatch.setenv('OPCUA_ALLOW_INSECURE','1')
    async def run():
        from asyncua import Server, ua
        with socket.socket() as probe:
            probe.bind(('127.0.0.1',0))
            port = probe.getsockname()[1]
        server = Server()
        await server.init()
        endpoint = f'opc.tcp://127.0.0.1:{port}/test'
        server.set_endpoint(endpoint)
        server.set_security_policy([ua.SecurityPolicyType.NoSecurity])
        namespace = await server.register_namespace('urn:landslide:test')
        node = await server.nodes.objects.add_variable(ua.NodeId('water',namespace), 'Water level', 2.75)
        async with server:
            payload = await bridge.read_device({'sensor_type':'water','profile':{'protocol':'opcua','endpoint':endpoint,'points':[{'field':'water_level','node_id':node.nodeid.to_string()}]}})
            assert payload == {'water_level':2.75}
    asyncio.run(run())
