"""Small durable append-only handoff for sensor batches.

The MQTT callback must stay available while a database is unavailable.  The
regular in-memory queue remains the fast path; this module gives failed
batches a process-restart boundary without changing the SensorData API.  Each
line is an envelope, so acknowledging a batch is an atomic rewrite rather
than an in-place mutation of a partially written row.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from ..config import settings

logger = logging.getLogger(__name__)


class IngestSpool:
    """Crash-tolerant JSONL spool with bounded disk usage.

    A torn final line is ignored on read and removed on the next compaction.
    Writes use flush+fsync and replacement uses os.replace, which is enough
    for the local durable handoff contract while keeping the implementation
    dependency-free.
    """

    def __init__(self, directory: str | os.PathLike[str] | None = None, max_bytes: int | None = None):
        configured = str(directory or getattr(settings, "INGEST_SPOOL_DIR", "") or "").strip()
        self.directory = Path(configured) if configured else Path(__file__).resolve().parents[3] / "runtime" / "ingest_spool"
        self.path = self.directory / "sensor_batches.jsonl"
        self.max_bytes = max(1024 * 1024, int(max_bytes or getattr(settings, "INGEST_SPOOL_MAX_BYTES", 256 * 1024 * 1024)))
        self._file_lock = threading.Lock()

    def _ensure_directory(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)

    def _iter_sync(self):
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as handle:
            for raw in handle:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    value = json.loads(raw)
                except json.JSONDecodeError:
                    # A power loss can leave a partial final line.  Keep
                    # earlier complete envelopes and let compaction remove it.
                    logger.warning("Ignoring torn ingest spool line")
                    continue
                if isinstance(value, dict) and value.get("batch_id") and isinstance(value.get("records"), list):
                    yield value

    def _read_sync(self, limit=None) -> list[dict[str, Any]]:
        rows = []
        for value in self._iter_sync():
            rows.append(value)
            if limit is not None and len(rows) >= limit:
                break
        return rows

    def _append_sync(self, batch_id: str, records: list[dict[str, Any]], reason: str | None) -> bool:
        payload = {
            "batch_id": str(batch_id),
            "created_at": int(time.time()),
            "reason": str(reason or "db_flush_failed")[:120],
            "records": records,
        }
        encoded = (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        with self._file_lock:
            self._ensure_directory()
            current_size = self.path.stat().st_size if self.path.exists() else 0
            if current_size + len(encoded) > self.max_bytes:
                return False
            with self.path.open("ab") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
        return True

    def _ack_sync(self, batch_ids: set[str]) -> None:
        if not batch_ids or not self.path.exists():
            return
        with self._file_lock:
            self._ensure_directory()
            tmp = self.path.with_suffix(f".tmp-{uuid.uuid4().hex}")
            retained = 0
            with tmp.open("w", encoding="utf-8", newline="\n") as handle:
                for row in self._iter_sync():
                    if str(row.get("batch_id")) in batch_ids:
                        continue
                    handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                    retained += 1
                handle.flush()
                os.fsync(handle.fileno())
            if retained:
                os.replace(tmp, self.path)
            else:
                tmp.unlink(missing_ok=True)
                self.path.unlink(missing_ok=True)

    async def append(self, batch_id: str, records: list[dict[str, Any]], reason: str | None = None) -> bool:
        return await asyncio.to_thread(self._append_sync, batch_id, records, reason)

    async def pending(self, limit: int = 1) -> list[dict[str, Any]]:
        def read() -> list[dict[str, Any]]:
            with self._file_lock:
                return self._read_sync(limit=max(1, int(limit)))
        return await asyncio.to_thread(read)

    async def acknowledge(self, *batch_ids: str) -> None:
        await asyncio.to_thread(self._ack_sync, {str(item) for item in batch_ids if item})

    async def stats(self) -> dict[str, Any]:
        def inspect() -> dict[str, Any]:
            with self._file_lock:
                batches = records = oldest = 0
                for row in self._iter_sync():
                    batches += 1
                    records += len(row.get("records") or [])
                    created = int(row.get("created_at") or 0)
                    oldest = min(oldest, created) if batches > 1 else created
                size = self.path.stat().st_size if self.path.exists() else 0
            return {
                "batches": batches,
                "records": records,
                "bytes": size,
                "oldest_age_seconds": max(0, int(time.time()) - oldest) if oldest else 0,
                "path": str(self.path),
            }
        return await asyncio.to_thread(inspect)
