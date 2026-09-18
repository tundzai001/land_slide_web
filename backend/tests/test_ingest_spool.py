import shutil
import unittest
from pathlib import Path
from uuid import uuid4

from app.infrastructure.ingest_spool import IngestSpool


class IngestSpoolTests(unittest.IsolatedAsyncioTestCase):
    def _workspace_temp_dir(self) -> Path:
        directory = Path(__file__).resolve().parent / f".ingest-spool-test-{uuid4().hex}"
        directory.mkdir(parents=True, exist_ok=False)
        return directory

    async def test_append_pending_ack_round_trip(self):
        directory = self._workspace_temp_dir()
        try:
            spool = IngestSpool(directory, max_bytes=1024 * 1024)
            records = [{"station_id": 1, "timestamp": 10, "sensor_type": "gnss", "data": {"x": 1}}]
            self.assertTrue(await spool.append("batch-a", records, "db_down"))
            self.assertEqual((await spool.pending())[0]["records"], records)
            stats = await spool.stats()
            self.assertEqual(stats["batches"], 1)
            self.assertEqual(stats["records"], 1)
            await spool.acknowledge("batch-a")
            self.assertEqual(await spool.pending(), [])
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    async def test_restart_reads_complete_lines_and_ignores_torn_tail(self):
        directory = self._workspace_temp_dir()
        try:
            spool = IngestSpool(directory)
            self.assertTrue(await spool.append("batch-b", [{"value": 2}]))
            path = Path(directory) / "sensor_batches.jsonl"
            with path.open("ab") as handle:
                handle.write(b'{"batch_id":"torn"')
            restarted = IngestSpool(directory)
            pending = await restarted.pending()
            self.assertEqual([row["batch_id"] for row in pending], ["batch-b"])
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    async def test_hard_limit_rejects_new_batch(self):
        directory = self._workspace_temp_dir()
        try:
            spool = IngestSpool(directory, max_bytes=1024 * 1024)
            self.assertFalse(await spool.append("too-large", [{"payload": "x" * (2 * 1024 * 1024)}]))
            self.assertEqual((await spool.stats())["batches"], 0)
        finally:
            shutil.rmtree(directory, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
