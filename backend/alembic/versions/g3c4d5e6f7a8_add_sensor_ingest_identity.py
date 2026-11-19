"""Add nullable idempotency identity for sensor ingest batches."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "g3c4d5e6f7a8"
down_revision: str | Sequence[str] | None = "f2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sensor_data", sa.Column("ingest_id", sa.String(length=64), nullable=True))
    op.create_index(
        "ix_sensor_data_ingest_id_unique",
        "sensor_data",
        ["ingest_id"],
        unique=True,
        postgresql_where=sa.text("ingest_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_sensor_data_ingest_id_unique", table_name="sensor_data")
    op.drop_column("sensor_data", "ingest_id")
