import unittest
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services import scheduler as scheduler_service


class _ProjectResult:
    def __init__(self, project):
        self.project = project

    def scalar_one_or_none(self):
        return self.project


class _ConfigSession:
    def __init__(self, project):
        self.project = project

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def execute(self, _statement):
        return _ProjectResult(self.project)


class AutoAdjustmentSchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def test_scheduled_run_enters_the_normal_adjustment_workflow(self):
        project = SimpleNamespace(
            id=12,
            auto_adjustment_config={
                "enabled": True,
                "selected_clusters": [1],
            },
            gnss_clusters=[
                {"name": "north", "stations": [1, 2]},
                {"name": "south", "stations": ["Dap4_2", "Dap4_1"]},
            ],
        )
        start_adjustment = AsyncMock(
            return_value={"phase": "COLLECTING_BASELINE", "existing": False}
        )

        with (
            patch.object(
                scheduler_service,
                "ConfigSessionLocal",
                return_value=_ConfigSession(project),
            ),
            patch.object(scheduler_service, "_start_normal_adjustment", start_adjustment),
        ):
            await scheduler_service.run_scheduled_adjustment(project.id)

        start_adjustment.assert_awaited_once()
        self.assertEqual(start_adjustment.await_args.args[0], project.id)
        self.assertEqual(start_adjustment.await_args.args[1], [["Dap4_2", "Dap4_1"]])
        self.assertIs(start_adjustment.await_args.args[2].project, project)

    async def test_scheduled_start_failure_is_persisted_without_escaping_job(self):
        project = SimpleNamespace(
            id=3,
            auto_adjustment_config={"enabled": True, "selected_clusters": [0]},
            gnss_clusters=[{"name": "dam", "stations": ["Dap1_4", "Dap1_3"]}],
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.object(
                    scheduler_service,
                    "ConfigSessionLocal",
                    return_value=_ConfigSession(project),
                ),
                patch.object(
                    scheduler_service.adjustment_failure,
                    "ADJUSTMENT_REPORT_DIR",
                    Path(temp_dir),
                ),
                patch.object(
                    scheduler_service,
                    "_start_normal_adjustment",
                    AsyncMock(side_effect=RuntimeError("receiver did not enter rover mode")),
                ),
            ):
                await scheduler_service.run_scheduled_adjustment(project.id)
                reports = list(Path(temp_dir).glob("gnss_adjustment_3_*.json"))
                self.assertEqual(len(reports), 1)
                payload = json.loads(reports[0].read_text(encoding="utf-8"))

        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["source"], "automatic_scheduler")
        self.assertEqual(payload["project_id"], project.id)
        self.assertEqual(payload["context"]["stage"], "start_adjustment")
        self.assertIn("receiver did not enter rover mode", payload["error"]["message"])


if __name__ == "__main__":
    unittest.main()
