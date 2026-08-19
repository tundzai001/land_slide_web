import json
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openpyxl import load_workbook

from app.services import adjustment_failure

_REPORTING_SPEC = importlib.util.spec_from_file_location(
    "adjustment_reporting",
    Path(__file__).parent / "processors" / "gnss_adjustment" / "reporting.py",
)
_REPORTING_MODULE = importlib.util.module_from_spec(_REPORTING_SPEC)
sys.modules[_REPORTING_SPEC.name] = _REPORTING_MODULE
_REPORTING_SPEC.loader.exec_module(_REPORTING_MODULE)


class AdjustmentFailureArtifactTests(unittest.TestCase):
    def test_each_cluster_gets_a_readable_independent_report_path(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp_dir, patch.object(
            adjustment_failure,
            "ADJUSTMENT_REPORT_DIR",
            Path(temp_dir),
        ):
            dam_one = adjustment_failure.write_adjustment_failure_report(
                3,
                "Dap1_3: no fresh AGRICA",
                source="automatic_scheduler",
                project_code="Sin_Quyen_2026",
                cluster_name="Đập 1",
            )
            dam_four = adjustment_failure.write_adjustment_failure_report(
                3,
                "Dap4_2: no fresh AGRICA",
                source="automatic_scheduler",
                project_code="Sin_Quyen_2026",
                cluster_name="Đập 4",
            )

            paths = list(Path(temp_dir).rglob("*.json"))
            self.assertEqual(len(paths), 2)
            self.assertEqual(len(list(Path(temp_dir).rglob("*.xlsx"))), 2)
            self.assertEqual(
                {path.parent.relative_to(temp_dir).as_posix() for path in paths},
                {"sin-quyen-2026/dap-1", "sin-quyen-2026/dap-4"},
            )
            self.assertIn("/sin-quyen-2026/dap-1/", dam_one["audit_json_url"])
            self.assertIn("/sin-quyen-2026/dap-4/", dam_four["audit_json_url"])
            payloads = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
            self.assertEqual({item["cluster_name"] for item in payloads}, {"Đập 1", "Đập 4"})

    def test_success_report_uses_the_same_project_cluster_scope(self):
        class _Writer(_REPORTING_MODULE.AdjustmentReportMixin):
            def _append_adjustment_to_excel(
                self,
                project_id,
                timestamp,
                data,
                raw_payload,
                report_directory=None,
                report_scope_name=None,
            ):
                path = Path(report_directory) / f"gnss_binh_sai_{report_scope_name}_{timestamp}.xlsx"
                path.write_bytes(b"xlsx")
                return str(path)

        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp_dir, patch.object(
            _REPORTING_MODULE,
            "BACKEND_DIR",
            Path(temp_dir),
        ):
            urls = _Writer()._write_adjustment_reports(3, 1786636800, {
                "project_code": "Sin_Quyen_2026",
                "cluster_name": "Đập 1",
                "run_id": -3001,
            })

            self.assertIn("/sin-quyen-2026/dap-1/2026-08-13/", urls["audit_json_url"])
            self.assertIn("/sin-quyen-2026/dap-1/2026-08-13/", urls["excel_report_url"])
            self.assertEqual(len(list(Path(temp_dir).rglob("*.json"))), 1)
            self.assertEqual(len(list(Path(temp_dir).rglob("*.xlsx"))), 1)

    def test_automatic_run_uses_a_date_folder_without_status_json(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp_dir, patch.object(
            adjustment_failure,
            "ADJUSTMENT_REPORT_DIR",
            Path(temp_dir),
        ):
            result = adjustment_failure.write_adjustment_failure_report(
                3,
                "Dap1_3: no stable window",
                source="automatic_scheduler",
                project_code="Sin_Quyen_2026",
                cluster_name="Đập 1",
                context={"run_id": -3001},
            )

            paths = list(Path(temp_dir).rglob("*.json"))
            self.assertEqual(len(paths), 1)
            self.assertEqual(
                paths[0].parent.parent.relative_to(temp_dir).as_posix(),
                "sin-quyen-2026/dap-1",
            )
            self.assertRegex(paths[0].parent.name, r"^\d{4}-\d{2}-\d{2}$")
            self.assertNotIn("run--3001", result["audit_json_url"])
            self.assertTrue(result["excel_report_url"].endswith(".xlsx"))

    def test_manual_run_also_uses_a_readable_date_folder(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp_dir, patch.object(
            adjustment_failure,
            "ADJUSTMENT_REPORT_DIR",
            Path(temp_dir),
        ):
            result = adjustment_failure.write_adjustment_failure_report(
                3,
                "manual preflight failed",
                source="manual",
                project_code="Sin_Quyen_2026",
                cluster_name="Đập 1",
                context={"run_id": 3},
            )

            report_path = next(Path(temp_dir).rglob("*.json"))
            self.assertRegex(report_path.parent.name, r"^\d{4}-\d{2}-\d{2}$")
            self.assertNotIn("run-3", result["audit_json_url"])

    def test_failure_xlsx_contains_reason_diagnostics_and_raw_gnss(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp_dir, patch.object(
            adjustment_failure,
            "ADJUSTMENT_REPORT_DIR",
            Path(temp_dir),
        ):
            result = adjustment_failure.write_adjustment_failure_report(
                3,
                "Position Type 1; requires 4 or 7",
                source="round_robin_runtime",
                project_code="Sin_Quyen_2026",
                cluster_name="Đập 1",
                context={
                    "run_id": -3001,
                    "diagnostics": {"raw_gnss": [{
                        "epoch_ts": 1786636800,
                        "station_id": 4,
                        "rover": "Dap1_4",
                        "position_type": 1,
                        "base": "BASE",
                        "solver_eligible": False,
                        "reason": "requires RTK Fixed",
                        "raw_payload": "#AGRICA,RAW-CHECK*00",
                    }]},
                },
            )

            workbook = load_workbook(next(Path(temp_dir).rglob("*.xlsx")), read_only=True)
            try:
                self.assertEqual(workbook.sheetnames, ["LOI_BINH_SAI", "RAW_GNSS", "CHAN_DOAN"])
                self.assertEqual(workbook["RAW_GNSS"]["D2"].value, 1)
                self.assertEqual(workbook["RAW_GNSS"]["H2"].value, "#AGRICA,RAW-CHECK*00")
            finally:
                workbook.close()
            self.assertIn(".xlsx", result["report_file_url"])


if __name__ == "__main__":
    unittest.main()
