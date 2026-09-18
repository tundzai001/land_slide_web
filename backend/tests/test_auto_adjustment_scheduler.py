import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.infrastructure import scheduler as scheduler_service


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
        self.assertEqual(start_adjustment.await_args.kwargs["run_id"], -12002)
        self.assertEqual(start_adjustment.await_args.kwargs["cluster_index"], 1)

    async def test_selected_disjoint_clusters_start_concurrently(self):
        project = SimpleNamespace(
            id=3,
            project_code="Sin_Quyen_2026",
            auto_adjustment_config={"enabled": True, "selected_clusters": [0, 1]},
            gnss_clusters=[
                {"name": "Đập 1", "stations": [1, 2, 3]},
                {"name": "Đập 4", "stations": [4, 5]},
            ],
        )
        active_calls = 0
        max_active_calls = 0
        start_order = []
        both_started = asyncio.Event()

        async def start_cluster(*_args, **_kwargs):
            nonlocal active_calls, max_active_calls
            from app.runtime import mqtt_service

            run_id = _kwargs["run_id"]
            start_order.append(run_id)
            active_calls += 1
            max_active_calls = max(max_active_calls, active_calls)
            if active_calls == 2:
                both_started.set()
            await asyncio.wait_for(both_started.wait(), timeout=1)
            active_calls -= 1
            mqtt_service.adjustment_run_contexts[run_id]["status"] = "COMPLETED"
            return {"phase": "COLLECTING_BASELINE"}

        with (
            patch.object(
                scheduler_service,
                "ConfigSessionLocal",
                return_value=_ConfigSession(project),
            ),
            patch.object(
                scheduler_service,
                "_start_normal_adjustment",
                AsyncMock(side_effect=start_cluster),
            ) as start_adjustment,
        ):
            await scheduler_service.run_scheduled_adjustment(project.id)

        self.assertEqual(start_adjustment.await_count, 2)
        self.assertEqual(max_active_calls, 2)
        self.assertEqual(set(start_order), {-3001, -3002})
        self.assertEqual(
            {call.kwargs["run_id"] for call in start_adjustment.await_args_list},
            {-3001, -3002},
        )
    async def test_scheduled_start_failure_is_persisted_without_escaping_job(self):
        project = SimpleNamespace(
            id=3,
            auto_adjustment_config={"enabled": True, "selected_clusters": [0]},
            gnss_clusters=[{"name": "dam", "stations": ["Dap1_4", "Dap1_3"]}],
        )

        payload = {
            "status": "failed",
            "source": "automatic_scheduler",
            "project_id": project.id,
            "cluster_name": "dam",
            "context": {"stage": "start_adjustment"},
            "error": {"message": "receiver did not enter rover mode"},
        }
        with (
            patch.object(
                scheduler_service,
                "ConfigSessionLocal",
                return_value=_ConfigSession(project),
            ),
            patch.object(
                scheduler_service,
                "_start_normal_adjustment",
                AsyncMock(side_effect=RuntimeError("receiver did not enter rover mode")),
            ),
            patch.object(
                scheduler_service,
                "write_adjustment_failure_report",
                AsyncMock(return_value=payload),
            ) as write_failure,
        ):
            await scheduler_service.run_scheduled_adjustment(project.id)

        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["source"], "automatic_scheduler")
        self.assertEqual(payload["project_id"], project.id)
        self.assertEqual(payload["cluster_name"], "dam")
        self.assertEqual(payload["context"]["stage"], "start_adjustment")
        self.assertIn("receiver did not enter rover mode", payload["error"]["message"])
        write_failure.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
