"""Persist deterministic simulation runs and their audit payloads.

The simulation API was introduced before its durable table had a migration.
Keeping this revision additive lets existing deployments roll forward without
changing the simulation request/response contract or engine physics.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f2b3c4d5e6f7"
down_revision: Union[str, Sequence[str], None] = "e1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "simulation_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("display_name", sa.String(240), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_by_username", sa.String(150), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("project_code", sa.String(80), nullable=True),
        sa.Column("project_name", sa.String(255), nullable=True),
        sa.Column("station_id", sa.Integer(), nullable=True),
        sa.Column("station_code", sa.String(80), nullable=True),
        sa.Column("station_name", sa.String(255), nullable=True),
        sa.Column("mode", sa.String(32), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="queued"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("engine_version", sa.String(32), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("seed", sa.BigInteger(), nullable=False),
        sa.Column("sim_duration_seconds", sa.Integer(), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("parameter_sources", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("sensor_snapshot", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("time_series", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("events", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("summary", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("terrain_profile", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("warnings", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("started_at", sa.BigInteger(), nullable=True),
        sa.Column("finished_at", sa.BigInteger(), nullable=True),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
    )
    op.create_index("ix_simulation_runs_created_by_user_id", "simulation_runs", ["created_by_user_id"])
    op.create_index("ix_simulation_runs_project_created", "simulation_runs", ["project_id", "created_at"])
    op.create_index("ix_simulation_runs_station_created", "simulation_runs", ["station_id", "created_at"])
    op.create_index("ix_simulation_runs_status_created", "simulation_runs", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_simulation_runs_status_created", table_name="simulation_runs")
    op.drop_index("ix_simulation_runs_station_created", table_name="simulation_runs")
    op.drop_index("ix_simulation_runs_project_created", table_name="simulation_runs")
    op.drop_index("ix_simulation_runs_created_by_user_id", table_name="simulation_runs")
    op.drop_table("simulation_runs")
