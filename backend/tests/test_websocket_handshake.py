"""The deployed SansIO handshake must send exactly one Date header to Nginx."""
import asyncio
import base64
import socket
import unittest

import uvicorn


class WebSocketHandshakeTests(unittest.IsolatedAsyncioTestCase):
    async def test_accepted_handshake_has_one_date_header(self):
        async def app(scope, receive, send):
            await receive()
            await send({'type':'websocket.accept'})
            while (await receive())['type'] != 'websocket.disconnect':
                pass

        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        listener.listen(8)
        server = uvicorn.Server(uvicorn.Config(app, ws='websockets-sansio', lifespan='off',
                                               log_config=None, access_log=False))
        task = asyncio.create_task(server.serve(sockets=[listener]))
        writer = None
        try:
            for _ in range(200):
                if server.started:
                    break
                if task.done():
                    await task
                await asyncio.sleep(.01)
            self.assertTrue(server.started, 'Test server did not start')
            reader, writer = await asyncio.open_connection('127.0.0.1', listener.getsockname()[1])
            key = base64.b64encode(b'0123456789abcdef').decode()
            writer.write(('GET / HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\n'
                'Connection: Upgrade\r\nSec-WebSocket-Version: 13\r\n'
                f'Sec-WebSocket-Key: {key}\r\n\r\n').encode())
            await writer.drain()
            headers = (await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 5)).decode().split('\r\n')
            self.assertIn('101 Switching Protocols', headers[0])
            self.assertEqual(sum(line.lower().startswith('date:') for line in headers), 1)
        finally:
            if writer:
                writer.close()
                await writer.wait_closed()
            server.should_exit = True
            await asyncio.wait_for(task, 5)
            listener.close()
