import unittest
import zipfile
from io import BytesIO

from openpyxl import Workbook, load_workbook

from app.routers.admin import (
    ExportExcelRequest,
    _excel_chunks,
    _excel_sheet_name,
    _package_workbook_zip,
    _station_export_path,
    _zip_component,
)


class ExcelExportHelpersTests(unittest.TestCase):
    def test_export_scope_accepts_project_station_and_sensor_filters(self):
        request = ExportExcelRequest(
            tables=["sensor_data"],
            project_ids=[2],
            station_ids=[7],
            sensor_types=["gnss"],
        )
        self.assertEqual(request.project_ids, [2])
        self.assertEqual(request.station_ids, [7])
        self.assertEqual(request.sensor_types, ["gnss"])

    def test_export_request_accepts_dedicated_gnss_adjustment_dataset(self):
        request = ExportExcelRequest(
            tables=["gnss_adjustments"],
            project_ids=[3],
            station_ids=[9],
            cluster_indices=[1],
        )

        self.assertEqual(request.tables, ["gnss_adjustments"])
        self.assertEqual(request.project_ids, [3])
        self.assertEqual(request.station_ids, [9])
        self.assertEqual(request.cluster_indices, [1])

    def test_sheet_names_are_valid_unique_and_within_excel_limit(self):
        used = set()
        first = _excel_sheet_name("PROJECT/VERY:LONG*STATION?GNSS_AUDIT", used)
        second = _excel_sheet_name("PROJECT/VERY:LONG*STATION?GNSS_AUDIT", used)

        self.assertLessEqual(len(first), 31)
        self.assertLessEqual(len(second), 31)
        self.assertNotEqual(first, second)
        self.assertFalse(any(char in first for char in '\\/*?:[]'))

    def test_large_payload_is_preserved_across_excel_cells(self):
        payload = "x" * 70000
        chunks = _excel_chunks(payload, 8)
        self.assertEqual("".join(chunk for chunk in chunks if chunk), payload)

    def test_zip_folder_components_are_safe_and_readable(self):
        self.assertEqual(_zip_component("Project A/B", "fallback"), "Project_A_B")
        self.assertEqual(_zip_component("..", "fallback"), "fallback")
        self.assertEqual(
            _station_export_path("Project A", "CP/01", 7, "GNSS.csv"),
            "Project_A/CP_01/GNSS.csv",
        )

    def test_one_workbook_can_hold_measurement_and_audit_sheets(self):
        workbook = Workbook(write_only=True)
        summary = workbook.create_sheet("EXPORT_SUMMARY")
        measurement = workbook.create_sheet("P1_ST1_gnss")
        audit = workbook.create_sheet("P1_ST1_gnss_audit")
        summary.append(["dataset", "record_count", "scope"])
        summary.append(["P1/ST1/gnss", 1, "FULL - no LIMIT"])
        measurement.append(["raw_gngga"])
        measurement.append(["$GNGGA,FIXED*00"])
        audit.append(["raw_gngga", "forward_payload"])
        audit.append(["$GNGGA,FLOAT*00", None])

        output = BytesIO()
        workbook.save(output)
        output.seek(0)
        loaded = load_workbook(output, read_only=True)

        self.assertEqual(
            loaded.sheetnames,
            ["EXPORT_SUMMARY", "P1_ST1_gnss", "P1_ST1_gnss_audit"],
        )

    def test_zip_contains_one_xlsx_with_all_sheets(self):
        workbook = Workbook(write_only=True)
        workbook.create_sheet("GNSS")
        workbook.create_sheet("GNSS_BAT_THUONG")
        output, xlsx_name = _package_workbook_zip(workbook, 123)

        with zipfile.ZipFile(output) as archive:
            self.assertEqual(archive.namelist(), [xlsx_name])
            loaded = load_workbook(BytesIO(archive.read(xlsx_name)), read_only=True)
        self.assertEqual(loaded.sheetnames, ["GNSS", "GNSS_BAT_THUONG"])


if __name__ == "__main__":
    unittest.main()
