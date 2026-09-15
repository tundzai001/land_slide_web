import importlib.util
from pathlib import Path
import unittest

from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa


class GnssAdjustmentLookupMigrationTests(unittest.TestCase):
    def test_backfill_marks_one_row_per_legacy_run(self):
        engine = sa.create_engine("sqlite://")
        metadata = sa.MetaData()
        sensor_data = sa.Table(
            "sensor_data",
            metadata,
            sa.Column("id", sa.BigInteger, primary_key=True),
            sa.Column("station_id", sa.Integer, nullable=False),
            sa.Column("timestamp", sa.BigInteger, nullable=False),
            sa.Column("sensor_type", sa.String, nullable=False),
            sa.Column("data", sa.JSON, nullable=False),
        )
        metadata.create_all(engine)
        rows = [
            {"id": 1, "station_id": 11, "timestamp": 100, "sensor_type": "gnss_adjusted", "data": {"project_id": 7, "cluster_index": 2, "computed_at": "2026-09-15T01:02:03Z"}},
            {"id": 2, "station_id": 12, "timestamp": 100, "sensor_type": "gnss_adjusted", "data": {"project_id": 7, "cluster_index": 2, "computed_at": "2026-09-15T01:02:03Z"}},
            {"id": 3, "station_id": 13, "timestamp": 101, "sensor_type": "gnss_adjusted", "data": {"project_id": 7, "cluster_index": 3, "computed_at": 101}},
        ]

        migration_path = Path(__file__).parent / "alembic" / "versions" / "h4d5e6f7a8b9_add_gnss_adjustment_lookup.py"
        spec = importlib.util.spec_from_file_location("gnss_lookup_migration", migration_path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)

        with engine.begin() as connection:
            connection.execute(sensor_data.insert(), rows)
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()
            marked = connection.execute(sa.text(
                "SELECT adjustment_project_id, adjustment_cluster_index "
                "FROM sensor_data WHERE adjustment_key IS NOT NULL ORDER BY adjustment_cluster_index"
            )).all()

        self.assertEqual(marked, [(7, 2), (7, 3)])


if __name__ == "__main__":
    unittest.main()
