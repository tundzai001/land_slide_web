"""Add indexed representative rows for GNSS adjustment history."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "h4d5e6f7a8b9"
down_revision: Union[str, Sequence[str], None] = "g3c4d5e6f7a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sensor_data", sa.Column("adjustment_key", sa.String(length=255), nullable=True))
    op.add_column("sensor_data", sa.Column("adjustment_project_id", sa.Integer(), nullable=True))
    op.add_column("sensor_data", sa.Column("adjustment_cluster_index", sa.Integer(), nullable=True))

    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(sa.text("""
            WITH ranked AS (
                SELECT
                    id,
                    COALESCE(data ->> 'project_id', '0') AS project_key,
                    COALESCE(data ->> 'cluster_index', '-1') AS cluster_key,
                    COALESCE(data ->> 'computed_at', timestamp::text) AS time_key,
                    ROW_NUMBER() OVER (
                        PARTITION BY
                            COALESCE(data ->> 'project_id', '0'),
                            COALESCE(data ->> 'cluster_index', '-1'),
                            COALESCE(data ->> 'computed_at', timestamp::text)
                        ORDER BY id DESC
                    ) AS row_rank
                FROM sensor_data
                WHERE sensor_type = 'gnss_adjusted'
            )
            UPDATE sensor_data AS target
            SET
                adjustment_key = 'legacy:' || md5(ranked.project_key || ':' || ranked.cluster_key || ':' || ranked.time_key),
                adjustment_project_id = CASE WHEN ranked.project_key ~ '^-?[0-9]+$' THEN ranked.project_key::integer END,
                adjustment_cluster_index = CASE WHEN ranked.cluster_key ~ '^-?[0-9]+$' THEN ranked.cluster_key::integer END
            FROM ranked
            WHERE target.id = ranked.id AND ranked.row_rank = 1
        """))
    elif dialect == "sqlite":
        op.execute(sa.text("""
            WITH ranked AS (
                SELECT
                    id,
                    COALESCE(json_extract(data, '$.project_id'), 0) AS project_key,
                    COALESCE(json_extract(data, '$.cluster_index'), -1) AS cluster_key,
                    COALESCE(json_extract(data, '$.computed_at'), timestamp) AS time_key,
                    ROW_NUMBER() OVER (
                        PARTITION BY
                            COALESCE(json_extract(data, '$.project_id'), 0),
                            COALESCE(json_extract(data, '$.cluster_index'), -1),
                            COALESCE(json_extract(data, '$.computed_at'), timestamp)
                        ORDER BY id DESC
                    ) AS row_rank
                FROM sensor_data
                WHERE sensor_type = 'gnss_adjusted'
            )
            UPDATE sensor_data
            SET
                adjustment_key = 'legacy:' || (SELECT project_key || ':' || cluster_key || ':' || time_key FROM ranked WHERE ranked.id = sensor_data.id),
                adjustment_project_id = (SELECT project_key FROM ranked WHERE ranked.id = sensor_data.id),
                adjustment_cluster_index = (SELECT cluster_key FROM ranked WHERE ranked.id = sensor_data.id)
            WHERE id IN (SELECT id FROM ranked WHERE row_rank = 1)
        """))

    marker = sa.text("adjustment_key IS NOT NULL")
    op.create_index(
        "ix_sensor_data_adjustment_page",
        "sensor_data",
        ["sensor_type", "timestamp"],
        postgresql_where=marker,
        sqlite_where=marker,
    )
    op.create_index(
        "ix_sensor_data_adjustment_cluster",
        "sensor_data",
        ["adjustment_project_id", "adjustment_cluster_index", "timestamp"],
        postgresql_where=marker,
        sqlite_where=marker,
    )
    op.create_index(
        "ix_sensor_data_adjustment_key_unique",
        "sensor_data",
        ["adjustment_key"],
        unique=True,
        postgresql_where=marker,
        sqlite_where=marker,
    )


def downgrade() -> None:
    op.drop_index("ix_sensor_data_adjustment_key_unique", table_name="sensor_data")
    op.drop_index("ix_sensor_data_adjustment_cluster", table_name="sensor_data")
    op.drop_index("ix_sensor_data_adjustment_page", table_name="sensor_data")
    op.drop_column("sensor_data", "adjustment_cluster_index")
    op.drop_column("sensor_data", "adjustment_project_id")
    op.drop_column("sensor_data", "adjustment_key")
