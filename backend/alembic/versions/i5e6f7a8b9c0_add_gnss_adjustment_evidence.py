"""Store GNSS raw adjustment evidence separately from result JSON."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "i5e6f7a8b9c0"
down_revision: Union[str, Sequence[str], None] = "h4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gnss_adjustment_evidence",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("adjustment_key", sa.String(length=255), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("cluster_index", sa.Integer(), nullable=True),
        sa.Column("timestamp", sa.BigInteger(), nullable=False),
        sa.Column("source_index", sa.Integer(), nullable=False),
        sa.Column("station_id", sa.Integer(), nullable=True),
        sa.Column("epoch_ts", sa.BigInteger(), nullable=True),
        sa.Column("raw_payload", sa.Text(), nullable=True),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "adjustment_key",
            "source_index",
            name="uq_gnss_adjustment_evidence_source",
        ),
    )
    op.create_index(
        "ix_gnss_adjustment_evidence_key_index",
        "gnss_adjustment_evidence",
        ["adjustment_key", "source_index"],
    )
    op.create_index(
        "ix_gnss_adjustment_evidence_project_ts",
        "gnss_adjustment_evidence",
        ["project_id", "timestamp"],
    )
    op.create_index(
        "ix_gnss_adjustment_evidence_project_id",
        "gnss_adjustment_evidence",
        ["project_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_gnss_adjustment_evidence_project_id",
        table_name="gnss_adjustment_evidence",
    )
    op.drop_index(
        "ix_gnss_adjustment_evidence_project_ts",
        table_name="gnss_adjustment_evidence",
    )
    op.drop_index(
        "ix_gnss_adjustment_evidence_key_index",
        table_name="gnss_adjustment_evidence",
    )
    op.drop_table("gnss_adjustment_evidence")
