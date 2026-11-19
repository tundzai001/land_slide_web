"""Add responsive-query indexes and project auto-adjustment config.

Revision ID: c7e920af14d2
Revises: b4a6f5d1c2e0

The deployment uses separate data/config databases. This revision is safe on
either target: it only creates indexes for tables present in the current DB.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "c7e920af14d2"
down_revision: str | Sequence[str] | None = "b4a6f5d1c2e0"
branch_labels = None
depends_on = None

INDEXES = (
    ("stations", "ix_stations_project_status", ["project_id", "status"]),
    ("devices", "ix_devices_station_active", ["station_id", "is_active"]),
    ("pi_devices", "ix_pi_devices_status_station_seen", ["status", "station_id", "last_seen"]),
)


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "projects" in tables:
        project_columns = {column["name"] for column in inspector.get_columns("projects")}
        if "auto_adjustment_config" not in project_columns:
            op.add_column(
                "projects",
                sa.Column("auto_adjustment_config", sa.JSON(), nullable=True),
            )
    for table, name, columns in INDEXES:
        if table in tables:
            op.create_index(name, table, columns, unique=False, if_not_exists=True)


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    for table, name, _columns in reversed(INDEXES):
        if table in tables:
            op.drop_index(name, table_name=table, if_exists=True)
    if "projects" in tables:
        project_columns = {column["name"] for column in inspector.get_columns("projects")}
        if "auto_adjustment_config" in project_columns:
            op.drop_column("projects", "auto_adjustment_config")
