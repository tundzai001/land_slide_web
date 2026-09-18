import asyncio
import unittest
from io import BytesIO
from unittest.mock import AsyncMock, patch

from openpyxl import load_workbook

from app.features.data_export.reports.adjustment import failure_workbook
from app.features.data_export.reports.adjustment.artifacts import adjustment_report_links
from app.features.gnss_adjustment import store as adjustment_store


class AdjustmentFailureArtifactTests(unittest.TestCase):
    def test_failure_is_compact_and_persisted_without_static_files(self):
        persist = AsyncMock(side_effect=lambda payload, **_kwargs: payload)
        with patch.object(adjustment_store, "persist_adjustment_snapshot", persist):
            result = asyncio.run(
                adjustment_store.write_adjustment_failure_report(
                    3,
                    "Position Type 1; requires 4 or 7",
                    source="round_robin_runtime",
                    project_code="Sin_Quyen_2026",
                    cluster_name="Đập 1",
                    context={
                        "run_id": -3001,
                        "diagnostics": {
                            "raw_gnss": [{
                                "epoch_ts": 1786636800,
                                "station_id": 4,
                                "raw_payload": "#AGRICA,RAW-CHECK*00",
                            }]
                        },
                    },
                )
            )

        self.assertEqual(result["status"], "failed")
        self.assertNotIn("raw_gnss", result["context"]["diagnostics"])
        self.assertEqual(
            persist.await_args.kwargs["sensor_type"],
            "gnss_adjustment_failed",
        )
        self.assertTrue(result["audit_json_url"].endswith(".json"))
        self.assertTrue(result["excel_report_url"].endswith(".xlsx"))

    def test_success_links_use_project_cluster_date_scope_without_files(self):
        links = adjustment_report_links(
            3,
            1786636800,
            project_code="Sin_Quyen_2026",
            cluster_name="Đập 1",
            run_id=-3001,
        )
        self.assertIn("/sin-quyen-2026/dap-1/2026-08-13/", links["audit_json_url"])
        self.assertIn("/sin-quyen-2026/dap-1/2026-08-13/", links["excel_report_url"])
        self.assertNotIn("run--3001", links["audit_json_url"])

    def test_failure_workbook_can_be_rendered_from_payload_on_demand(self):
        payload = {
            "status": "failed",
            "timestamp": 1786636800,
            "project_id": 3,
            "project_code": "Sin_Quyen_2026",
            "cluster_name": "Đập 1",
            "source": "round_robin_runtime",
            "error": {"type": "AdjustmentError", "message": "bad input"},
            "context": {
                "diagnostics": {
                    "raw_gnss": [{
                        "epoch_ts": 1786636800,
                        "station_id": 4,
                        "raw_payload": "#AGRICA,RAW-CHECK*00",
                    }]
                }
            },
        }
        output = BytesIO()
        failure_workbook._write_failure_workbook(output, payload)
        workbook = load_workbook(output, read_only=True)
        try:
            self.assertEqual(
                workbook.sheetnames,
                ["LOI_BINH_SAI", "RAW_GNSS", "CHAN_DOAN"],
            )
            self.assertEqual(workbook["RAW_GNSS"]["H2"].value, "#AGRICA,RAW-CHECK*00")
        finally:
            workbook.close()


if __name__ == "__main__":
    unittest.main()
