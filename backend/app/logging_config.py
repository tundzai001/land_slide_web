"""Process-wide logging and Windows console configuration."""
import logging
import os
import re
import sys

LOG_FILE_NAME = "landslide_system.log"
_ORIGINAL_STDOUT = sys.__stdout__


def configure_system_logging() -> None:
    if os.name == "nt":
        os.system("chcp 65001 >nul")
    if hasattr(_ORIGINAL_STDOUT, "reconfigure"):
        try:
            _ORIGINAL_STDOUT.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(logging.INFO)

    file_handler = logging.FileHandler(LOG_FILE_NAME, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler(_ORIGINAL_STDOUT)
    stream_handler.setFormatter(formatter)
    root_logger.addHandler(stream_handler)
    logging.captureWarnings(True)

    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
        framework_logger = logging.getLogger(logger_name)
        framework_logger.handlers.clear()
        framework_logger.propagate = True
        framework_logger.setLevel(logging.INFO)


def disable_windows_quick_edit_mode() -> None:
    """Prevent accidental console clicks from pausing the process on Windows."""
    if os.name != "nt":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-10)  # STD_INPUT_HANDLE
        if handle in (0, -1):
            return
        mode = ctypes.c_uint()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return
        enable_quick_edit = 0x0040
        enable_extended_flags = 0x0080
        new_mode = (mode.value | enable_extended_flags) & ~enable_quick_edit
        if new_mode != mode.value:
            kernel32.SetConsoleMode(handle, new_mode)
            logging.getLogger(__name__).info("Windows Quick Edit mode disabled")
    except Exception as exc:
        logging.getLogger(__name__).warning("Cannot disable Quick Edit mode: %s", exc)


class HeartbeatFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "/api/field/heartbeat" not in record.getMessage()


class SensitiveQueryFilter(logging.Filter):
    """Keep short-lived WebSocket credentials out of access logs."""

    _sensitive_query = re.compile(r"(?i)([?&](?:ticket|access_token)=)[^&\s\"']+")

    @classmethod
    def _redact(cls, value: str) -> str:
        return cls._sensitive_query.sub(r"\1<redacted>", value)

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self._redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(
                self._redact(value) if isinstance(value, str) else value
                for value in record.args
            )
        elif isinstance(record.args, dict):
            record.args = {
                key: self._redact(value) if isinstance(value, str) else value
                for key, value in record.args.items()
            }
        return True


def install_heartbeat_filter() -> None:
    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, HeartbeatFilter) for item in access_logger.filters):
        access_logger.addFilter(HeartbeatFilter())
    if not any(isinstance(item, SensitiveQueryFilter) for item in access_logger.filters):
        access_logger.addFilter(SensitiveQueryFilter())
