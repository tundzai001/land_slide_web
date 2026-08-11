import unittest
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
                {"name": "south", "stations": [3, 4]},
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
            patch(
                "app.routers.gnss_adjustment.start_gnss_adjustment",
                start_adjustment,
            ),
        ):
            await scheduler_service.run_scheduled_adjustment(project.id)

        start_adjustment.assert_awaited_once()
        request = start_adjustment.await_args.args[0]
        self.assertEqual(request.project_id, project.id)
        self.assertEqual(request.selected_clusters, [[3, 4]])
        self.assertEqual(start_adjustment.await_args.kwargs["current_user"].role, "system")


if __name__ == "__main__":
    unittest.main()
