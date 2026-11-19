"""Store operational logs and settings in the PostgreSQL data database."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'j6f7a8b9c0d1'
down_revision: str | Sequence[str] | None = 'i5e6f7a8b9c0'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create_log_table(name):
    op.create_table(
        name,
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('timestamp', sa.BigInteger(), nullable=False),
        sa.Column('username', sa.String(150), nullable=True),
        sa.Column('role', sa.String(32), nullable=True),
        sa.Column('action', sa.String(255), nullable=False),
        sa.Column('object', sa.String(500), nullable=True),
        sa.Column('ip', sa.String(64), nullable=True),
        sa.Column('status', sa.Integer(), nullable=True),
        sa.Column('details', sa.JSON(), nullable=False),
    )
    op.create_index(f'ix_{name}_timestamp_id', name, ['timestamp', 'id'])
    op.create_index(f'ix_{name}_username_timestamp', name, ['username', 'timestamp'])


def upgrade() -> None:
    _create_log_table('audit_log')
    _create_log_table('operation_log')
    op.create_table(
        'operations_settings',
        sa.Column('key', sa.String(200), primary_key=True),
        sa.Column('value', sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('operations_settings')
    op.drop_table('operation_log')
    op.drop_table('audit_log')
