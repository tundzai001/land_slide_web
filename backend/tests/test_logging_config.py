import logging
import unittest

from app.logging_config import SensitiveQueryFilter, install_heartbeat_filter


class SensitiveQueryFilterTests(unittest.TestCase):
    def test_websocket_accept_logger_installs_credential_redaction(self):
        logger = logging.getLogger('uvicorn.error')
        original_filters = logger.filters[:]
        try:
            logger.filters.clear()
            install_heartbeat_filter()
            record = logging.LogRecord('uvicorn.error', logging.INFO, __file__, 1,
                                       'WebSocket %s [accepted]', ('/ws/admin?ticket=secret.jwt',), None)
            self.assertTrue(logger.filter(record))
            self.assertNotIn('secret.jwt', record.getMessage())
        finally:
            logger.filters[:] = original_filters

    def test_redacts_websocket_credentials_from_uvicorn_access_args(self):
        record = logging.LogRecord(
            "uvicorn.access",
            logging.INFO,
            __file__,
            1,
            '%s - "%s %s HTTP/%s" %d',
            (
                "127.0.0.1:1234",
                "WebSocket",
                "/ws/admin?ticket=secret.jwt&channel=admin",
                "1.1",
                101,
            ),
            None,
        )

        self.assertTrue(SensitiveQueryFilter().filter(record))
        self.assertNotIn("secret.jwt", record.getMessage())
        self.assertIn("ticket=<redacted>", record.getMessage())

    def test_redacts_direct_access_message_without_damaging_quotes(self):
        record = logging.LogRecord(
            "uvicorn.access",
            logging.INFO,
            __file__,
            1,
            'WebSocket "/ws/operations?ticket=secret.jwt" [accepted]',
            (),
            None,
        )

        SensitiveQueryFilter().filter(record)
        self.assertEqual(
            record.getMessage(),
            'WebSocket "/ws/operations?ticket=<redacted>" [accepted]',
        )


if __name__ == "__main__":
    unittest.main()
