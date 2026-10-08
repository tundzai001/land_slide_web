"""Exercise the actual pinned driver protocol, including late SSL responses."""

import asyncio
import gc
import ssl
import unittest
from unittest.mock import patch

from asyncpg import connect_utils

from app.infrastructure.asyncpg_compat import install_asyncpg_tls_fix


class AsyncpgTLSCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.original = connect_utils.TLSUpgradeProto
        self.addCleanup(setattr, connect_utils, "TLSUpgradeProto", self.original)
        install_asyncpg_tls_fix()
        self.loop = asyncio.get_running_loop()

    def protocol(self, advisory=True):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        if advisory:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        return connect_utils.TLSUpgradeProto(
            self.loop, "localhost", 5432, context, advisory,
        )

    async def test_late_reply_after_timeout_or_completion(self):
        for response in (b"N", b"S", b"invalid"):
            for cancelled in (True, False):
                with self.subTest(response=response, cancelled=cancelled):
                    protocol = self.protocol()
                    if cancelled:
                        protocol.on_data.cancel()
                    else:
                        protocol.on_data.set_result(True)
                    protocol.data_received(response)
                    protocol.connection_lost(None)
                    self.assertEqual(protocol.on_data.cancelled(), cancelled)
                    if not cancelled:
                        self.assertTrue(await protocol.on_data)

    async def test_ssl_acceptance_and_advisory_refusal_unchanged(self):
        for response, expected in ((b"S", True), (b"N", False)):
            protocol = self.protocol()
            protocol.data_received(response)
            self.assertIs(await protocol.on_data, expected)

    async def test_required_ssl_still_rejects_plaintext(self):
        protocol = self.protocol(advisory=False)
        protocol.data_received(b"N")
        with self.assertRaisesRegex(ConnectionError, "rejected SSL upgrade"):
            await protocol.on_data

    async def test_connection_loss_still_reaches_awaiter(self):
        protocol = self.protocol()
        error = ConnectionResetError("synthetic disconnect")
        protocol.connection_lost(error)
        await asyncio.sleep(0)  # retrieval callback must not swallow await errors
        with self.assertRaises(ConnectionResetError) as caught:
            await protocol.on_data
        self.assertIs(caught.exception, error)

    async def test_orphaned_negotiation_has_no_unretrieved_exception(self):
        errors = []
        previous = self.loop.get_exception_handler()
        self.loop.set_exception_handler(lambda loop, context: errors.append(context))
        try:
            protocol = self.protocol()
            protocol.connection_lost(None)
            await asyncio.sleep(0)
            del protocol
            gc.collect()
            await asyncio.sleep(0)
            self.assertEqual(errors, [])
        finally:
            self.loop.set_exception_handler(previous)

    async def test_install_is_idempotent_and_version_scoped(self):
        installed = connect_utils.TLSUpgradeProto
        install_asyncpg_tls_fix()
        self.assertIs(connect_utils.TLSUpgradeProto, installed)
        connect_utils.TLSUpgradeProto = self.original
        with patch("app.infrastructure.asyncpg_compat.asyncpg.__version__", "future-version"):
            install_asyncpg_tls_fix()
        self.assertIs(connect_utils.TLSUpgradeProto, self.original)
