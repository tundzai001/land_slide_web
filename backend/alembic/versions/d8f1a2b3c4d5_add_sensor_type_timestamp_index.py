"""Add the sensor type/timestamp index used by the data explorer.

Revision ID: d8f1a2b3c4d5
Revises: c7e920af14d2
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect


revision: str = "d8f1a2b3c4d5"
down_revision: str | Sequence[str] | None = "c7e920af14d2"
branch_labels = None
depends_on = None

INDEX_NAME = "ix_sensor_data_type_ts"


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    if "sensor_data" not in inspector.get_table_names():
        return
    if INDEX_NAME not in {item["name"] for item in inspector.get_indexes("sensor_data")}:
        op.create_index(INDEX_NAME, "sensor_data", ["sensor_type", "timestamp"])


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    if "sensor_data" in inspector.get_table_names():
        if INDEX_NAME in {item["name"] for item in inspector.get_indexes("sensor_data")}:
            op.drop_index(INDEX_NAME, table_name="sensor_data")
