"""Add the additive Incident & Response domain tables.

The legacy alerts/rescue tables remain untouched.  These tables are deliberately
soft-linked across the Auth/Config databases so the Data database migration can
run independently and the API can enforce scope without cross-database FKs.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e1a2b3c4d5e6"
down_revision: str | None = "d8f1a2b3c4d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "incident_cases",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("reference", sa.String(40), nullable=False),
        sa.Column("source_kind", sa.String(24), nullable=False),
        sa.Column("source_id", sa.BigInteger(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("station_id", sa.Integer(), nullable=True),
        sa.Column("scope_state", sa.String(20), nullable=False, server_default="LOOKUP_PENDING"),
        sa.Column("project_name_snapshot", sa.String(255), nullable=True),
        sa.Column("project_code_snapshot", sa.String(100), nullable=True),
        sa.Column("station_name_snapshot", sa.String(255), nullable=True),
        sa.Column("station_code_snapshot", sa.String(100), nullable=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("source_severity", sa.String(16), nullable=False, server_default="UNKNOWN"),
        sa.Column("signal_state", sa.String(16), nullable=False, server_default="UNKNOWN"),
        sa.Column("priority", sa.String(16), nullable=False, server_default="UNTRIAGED"),
        sa.Column("status", sa.String(24), nullable=False, server_default="new"),
        sa.Column("assigned_to_user_id", sa.Integer(), nullable=True),
        sa.Column("assigned_to_username", sa.String(150), nullable=True),
        sa.Column("opened_at", sa.BigInteger(), nullable=False),
        sa.Column("last_signal_at", sa.BigInteger(), nullable=False),
        sa.Column("acknowledged_at", sa.BigInteger(), nullable=True),
        sa.Column("resolved_at", sa.BigInteger(), nullable=True),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("revision", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("last_event_sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("reference", name="uq_incident_reference"),
        sa.UniqueConstraint("source_kind", "source_id", name="uq_incident_source"),
    )
    op.create_index("ix_incident_attention", "incident_cases", ["status", "priority", "updated_at", "id"])
    op.create_index("ix_incident_scope_status", "incident_cases", ["project_id", "status", "updated_at", "id"])
    op.create_index("ix_incident_station_status", "incident_cases", ["station_id", "status", "updated_at", "id"])
    op.create_index("ix_incident_signal", "incident_cases", ["source_severity", "signal_state", "updated_at", "id"])
    op.create_index(
        "ix_incident_lookup_pending",
        "incident_cases",
        ["updated_at", "id"],
        postgresql_where=sa.text("scope_state = 'LOOKUP_PENDING'"),
    )
    op.create_index("ix_incident_cases_reference", "incident_cases", ["reference"])
    op.create_index("ix_incident_cases_project_id", "incident_cases", ["project_id"])
    op.create_index("ix_incident_cases_station_id", "incident_cases", ["station_id"])
    op.create_index("ix_incident_cases_assigned_to_user_id", "incident_cases", ["assigned_to_user_id"])

    op.create_table(
        "incident_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("incident_id", sa.BigInteger(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("actor_kind", sa.String(16), nullable=False, server_default="system"),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("actor_username", sa.String(150), nullable=True),
        sa.Column("project_id_at_event", sa.Integer(), nullable=True),
        sa.Column("previous_project_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("mutation_request_id", sa.BigInteger(), nullable=True),
        sa.UniqueConstraint("incident_id", "sequence", name="uq_incident_event_sequence"),
    )
    op.create_index("ix_incident_events_incident_id", "incident_events", ["incident_id"])
    op.create_index("ix_incident_events_case_created", "incident_events", ["incident_id", "created_at", "id"])
    op.create_index("ix_incident_events_project_cursor", "incident_events", ["project_id_at_event", "id"])

    op.create_table(
        "incident_mutation_requests",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("incident_id", sa.BigInteger(), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("action", sa.String(48), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("sequence_from", sa.Integer(), nullable=True),
        sa.Column("sequence_to", sa.Integer(), nullable=True),
        sa.Column("result_revision", sa.BigInteger(), nullable=True),
        sa.Column("result_version", sa.Integer(), nullable=True),
        sa.Column("changed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.UniqueConstraint("incident_id", "actor_user_id", "idempotency_key", name="uq_incident_mutation_key"),
    )
    op.create_index("ix_incident_mutation_requests_incident_id", "incident_mutation_requests", ["incident_id"])
    op.create_index("ix_incident_mutation_incident", "incident_mutation_requests", ["incident_id", "created_at"])

    op.create_table(
        "file_cleanup_jobs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("upload_id", sa.String(36), nullable=False),
        sa.Column("image_storage_key", sa.String(255), nullable=True),
        sa.Column("job_generation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("run_after", sa.BigInteger(), nullable=False),
        sa.Column("lease_owner", sa.String(64), nullable=True),
        sa.Column("lease_until", sa.BigInteger(), nullable=True),
        sa.Column("lease_generation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.Column("last_error_code", sa.String(64), nullable=True),
        sa.UniqueConstraint("upload_id", "job_generation", name="uq_cleanup_upload_generation"),
    )
    op.create_index("ix_cleanup_status_run_after", "file_cleanup_jobs", ["status", "run_after"])


def downgrade() -> None:
    op.drop_index("ix_cleanup_status_run_after", table_name="file_cleanup_jobs")
    op.drop_table("file_cleanup_jobs")
    op.drop_index("ix_incident_mutation_incident", table_name="incident_mutation_requests")
    op.drop_index("ix_incident_mutation_requests_incident_id", table_name="incident_mutation_requests")
    op.drop_table("incident_mutation_requests")
    op.drop_index("ix_incident_events_project_cursor", table_name="incident_events")
    op.drop_index("ix_incident_events_case_created", table_name="incident_events")
    op.drop_index("ix_incident_events_incident_id", table_name="incident_events")
    op.drop_table("incident_events")
    for index_name in (
        "ix_incident_cases_assigned_to_user_id",
        "ix_incident_cases_station_id",
        "ix_incident_cases_project_id",
        "ix_incident_cases_reference",
        "ix_incident_lookup_pending",
        "ix_incident_signal",
        "ix_incident_station_status",
        "ix_incident_scope_status",
        "ix_incident_attention",
    ):
        op.drop_index(index_name, table_name="incident_cases")
    op.drop_table("incident_cases")
