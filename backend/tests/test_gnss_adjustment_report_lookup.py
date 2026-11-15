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
        self.db.add_all([
            model_data.SensorData(
                id=1,
                station_id=5,
                timestamp=99,
                sensor_type="gnss_adjusted",
                adjustment_key="run:17:4:0",
                adjustment_project_id=17,
                data={"project_id": 17, "excel_report_url": "/another-report.xlsx"},
            ),
            model_data.SensorData(
                id=2,
                station_id=5,
                timestamp=100,
                sensor_type="gnss_adjusted",
                adjustment_key="run:17:4:1",
                adjustment_project_id=17,
                data={"project_id": 17, "excel_report_url": url},
            ),
        ])
        self.db.commit()

        found = await find_adjustment(
            self.session,
            project_id=17,
            requested_url=url,
        )

        self.assertIsNotNone(found)
        self.assertEqual(found[0].id, 2)
        query = str(self.session.statements[0].compile(dialect=sqlite_dialect()))
        self.assertIn("adjustment_project_id = ?", query)
        self.assertIn("adjustment_key IS NOT NULL", query)
        self.assertNotIn("json_extract", query.lower())

    async def test_selected_record_id_uses_primary_key_and_validates_report(self):
        url = "/api/admin/gnss/adjustment/reports/sin-quyen/dap-4/gnss_adjustment.xlsx"
        self.db.add(model_data.SensorData(
            id=2,
            station_id=5,
            timestamp=100,
            sensor_type="gnss_adjusted",
            adjustment_key="run:17:4:1",
            adjustment_project_id=17,
            data={"project_id": 17, "excel_report_url": url},
        ))
        self.db.add(model_data.SensorData(
            id=3,
            station_id=5,
            timestamp=101,
            sensor_type="gnss_adjusted",
            adjustment_key="run:18:4:1",
            adjustment_project_id=18,
            data={"project_id": 17, "excel_report_url": url},
        ))
        self.db.commit()

        found = await find_adjustment(
            self.session,
            project_id=17,
            requested_url=url,
            sensor_data_id=2,
        )

        self.assertIsNotNone(found)
        self.assertEqual(found[0].id, 2)
        query = str(self.session.statements[0].compile(dialect=sqlite_dialect()))
        self.assertIn("sensor_data.id = ?", query)
        self.assertNotIn("json_extract", query.lower())

        wrong_report = await find_adjustment(
            self.session,
            project_id=17,
            requested_url="/another-report.xlsx",
            sensor_data_id=2,
        )
        self.assertIsNone(wrong_report)
        wrong_project = await find_adjustment(
            self.session,
            project_id=17,
            requested_url=url,
            sensor_data_id=3,
        )
        self.assertIsNone(wrong_project)
        self.assertEqual(len(self.session.statements), 4)

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
        self.assertIn("json_extract", fallback.lower())
        self.assertIn("ORDER BY sensor_data.timestamp DESC", fallback)
        self.assertIn("LIMIT", fallback)

    async def test_evidence_query_timeout_is_not_swallowed_and_keeps_its_phase(self):
        url = "/api/admin/gnss/adjustment/reports/project/dap/gnss_adjustment.xlsx"
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

        class TimeoutOnEvidence(_AsyncSessionAdapter):
            async def execute(inner_self, statement):
                if len(inner_self.statements) == 1:
                    inner_self.statements.append(statement)
                    raise TimeoutError("evidence query timed out")
                return await super(TimeoutOnEvidence, inner_self).execute(statement)

        phases = []
        timeout_session = TimeoutOnEvidence(self.db)
        with self.assertRaisesRegex(TimeoutError, "evidence query timed out"):
            await find_adjustment(
                timeout_session,
                project_id=17,
                requested_url=url,
                request_id="request-test",
                mark_phase=phases.append,
            )

        self.assertEqual(phases, ["lookup_indexed_adjustment", "load_adjustment_evidence"])


if __name__ == "__main__":
    unittest.main()
