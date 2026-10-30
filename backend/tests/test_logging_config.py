import logging
import unittest
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from logging.handlers import RotatingFileHandler

from app import logging_config
from app.logging_config import SensitiveQueryFilter, install_heartbeat_filter


class LogRotationTests(unittest.TestCase):
    def test_rotation_bounds_backups_and_preserves_existing_log(self):
        root = logging.Logger("rotation-test", logging.INFO)
        framework = {name: logging.Logger(name) for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi")}
        with TemporaryDirectory() as directory:
            path = Path(directory) / "system.log"
            original = "Existing production history\n" * 20
            path.write_text(original, encoding="utf-8")
            with (
                patch.object(logging_config, "LOG_FILE_NAME", str(path)),
                patch.object(logging_config, "LOG_MAX_BYTES", 256),
                patch.object(logging_config, "LOG_BACKUP_COUNT", 2),
                patch.object(logging_config, "_ORIGINAL_STDOUT", StringIO()),
                patch.object(logging_config.logging, "captureWarnings"),
                patch.object(logging_config.logging, "getLogger", side_effect=lambda name=None: root if name is None else framework[name]),
            ):
                logging_config.configure_system_logging()
                first = next(handler for handler in root.handlers if isinstance(handler, RotatingFileHandler))
                root.info("Dữ liệu mới")
                self.assertEqual(Path(str(path) + ".1").read_text(encoding="utf-8"), original)
                logging_config.configure_system_logging()
                self.assertIsNone(first.stream)
                try:
                    for index in range(20):
                        root.warning("Cảnh báo %s: %s", index, "x" * 40)
                finally:
                    for handler in root.handlers:
                        handler.close()
                self.assertEqual(len(list(Path(directory).iterdir())), 3)
                self.assertLessEqual(sum(item.stat().st_size for item in Path(directory).iterdir()), 3 * 256)


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
