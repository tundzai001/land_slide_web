import unittest
import importlib.util
import sys
from pathlib import Path

_SESSION_SPEC = importlib.util.spec_from_file_location(
    "round_robin_session",
    Path(__file__).resolve().parents[1]
    / "processors"
    / "gnss_adjustment"
    / "session.py",
)
_SESSION_MODULE = importlib.util.module_from_spec(_SESSION_SPEC)
sys.modules[_SESSION_SPEC.name] = _SESSION_MODULE
_SESSION_SPEC.loader.exec_module(_SESSION_MODULE)
RoundRobinSessionLifecycleMixin = _SESSION_MODULE.RoundRobinSessionLifecycleMixin
requires_common_base_handover = _SESSION_MODULE.requires_common_base_handover


class _Manager(RoundRobinSessionLifecycleMixin):
    def __init__(self):
        self.running_tasks = {}
        self._sessions = {}
        self._last_ingest_diagnostics = {}
        self._ingest_warning_last_logged = {}
        self._agrica_fragment_buffers = {}


class RoundRobinSessionLifecycleTests(unittest.TestCase):
    def test_only_total_cluster_requires_common_base_handover(self):
        self.assertFalse(requires_common_base_handover({"cluster_type": "normal"}))
        self.assertFalse(requires_common_base_handover({}))
        self.assertTrue(requires_common_base_handover({"cluster_type": "total"}))

    def test_parallel_cluster_runs_keep_independent_sessions(self):
        manager = _Manager()
        manager.configure_project(-3001, [{
            "name": "Đập 1",
            "stations": [1, 2, 3],
            "rovers": ["Dap1_1", "Dap1_2", "Dap1_3"],
        }])
        manager.configure_project(-3002, [{
            "name": "Đập 4",
            "stations": [4, 5],
            "rovers": ["Dap4_1", "Dap4_2"],
        }])

        self.assertEqual(set(manager._sessions), {-3001, -3002})
        self.assertEqual(manager._sessions[-3001]["clusters"][0]["name"], "Đập 1")
        self.assertEqual(manager._sessions[-3002]["clusters"][0]["name"], "Đập 4")
        manager.clear_project(-3001)
        self.assertNotIn(-3001, manager._sessions)
        self.assertIn(-3002, manager._sessions)


if __name__ == "__main__":
    unittest.main()
