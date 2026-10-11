import unittest

from sqlalchemy import create_engine
from sqlalchemy.dialects.sqlite import dialect as sqlite_dialect
from sqlalchemy.orm import Session

from app.features.data_export.reports.adjustment.render import find_adjustment
from app.models import data as model_data


class _AsyncSessionAdapter:
    def __init__(self, session):
        self.session = session
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return self.session.execute(statement)


class GnssAdjustmentReportLookupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        model_data.SensorData.__table__.create(self.engine)
        model_data.GnssAdjustmentEvidence.__table__.create(self.engine)
        self.db = Session(self.engine)
        self.session = _AsyncSessionAdapter(self.db)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    async def test_indexed_report_lookup_matches_json_url(self):
        url = "/api/admin/gnss/adjustment/reports/sin-quyen/dap-4/gnss_adjustment.xlsx"
        self.db.add(model_data.SensorData(
            id=1,
            station_id=5,
            timestamp=100,
            sensor_type="gnss_adjusted",
            adjustment_key="run:17:4:1",
            adjustment_project_id=17,
            data={"project_id": 17, "excel_report_url": url},
        ))
        self.db.commit()

        found = await find_adjustment(
            self.session,
            project_id=17,
            requested_url=url,
        )

        self.assertIsNotNone(found)
        self.assertEqual(found[0].id, 1)
        query = str(self.session.statements[0].compile(dialect=sqlite_dialect()))
        self.assertIn("adjustment_project_id = ?", query)
        self.assertIn("adjustment_key IS NOT NULL", query)
        self.assertIn("json_extract", query.lower())
        self.assertIn("LIMIT", query)

    async def test_legacy_project_id_in_json_uses_fallback(self):
        url = "/api/admin/gnss/adjustment/reports/legacy/dap-4/gnss_adjustment.xlsx"
        self.db.add(model_data.SensorData(
            id=1,
            station_id=5,
            timestamp=100,
            sensor_type="gnss_adjusted",
            data={"project_id": 17, "excel_report_url": url},
        ))
        self.db.commit()

        found = await find_adjustment(
            self.session,
            project_id=17,
            requested_url=url,
        )

        self.assertIsNotNone(found)
        self.assertEqual(found[0].id, 1)
        self.assertEqual(len(self.session.statements), 2)
        fallback = str(self.session.statements[1].compile(dialect=sqlite_dialect()))
        self.assertIn("adjustment_project_id IS NULL", fallback)
        self.assertIn("ORDER BY sensor_data.timestamp DESC", fallback)
        self.assertIn("LIMIT", fallback)


if __name__ == "__main__":
    unittest.main()
