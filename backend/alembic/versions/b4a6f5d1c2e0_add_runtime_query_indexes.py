"""Add indexes used by station overview and active-alert queries.

Revision ID: b4a6f5d1c2e0
Revises: 88c875be05eb
"""

from typing import Sequence, Union

from alembic import op


revision: str = "b4a6f5d1c2e0"
down_revision: Union[str, Sequence[str], None] = "88c875be05eb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # CONCURRENTLY avoids blocking sensor ingestion on a populated production DB.
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_alerts_station_unresolved_ts",
            "alerts",
            ["station_id", "is_resolved", "timestamp"],
            unique=False,
            postgresql_concurrently=True,
            if_not_exists=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_alerts_station_unresolved_ts",
            table_name="alerts",
            postgresql_concurrently=True,
            if_exists=True,
        )
