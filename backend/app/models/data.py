#backend/app/models/data.py
from sqlalchemy import Column, Integer, String, Boolean, JSON, BigInteger, Float, Index, Text, UniqueConstraint, text
from app.database import BaseData

class SensorData(BaseData):

    __tablename__ = "sensor_data"
    # Composite index tối ưu cho truy vấn lịch sử theo trạm + loại sensor + thời gian
    __table_args__ = (
        Index('ix_sensor_data_station_type_ts', 'station_id', 'sensor_type', 'timestamp'),
        Index('ix_sensor_data_station_ts', 'station_id', 'timestamp'),
        Index('ix_sensor_data_type_ts', 'sensor_type', 'timestamp'),
        Index(
            'ix_sensor_data_ingest_id_unique',
            'ingest_id',
            unique=True,
            postgresql_where=text('ingest_id IS NOT NULL'),
            sqlite_where=text('ingest_id IS NOT NULL'),
        ),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)  # BigInteger cho dữ liệu lớn
    station_id = Column(Integer, index=True, nullable=False)
    timestamp = Column(BigInteger, index=True, nullable=False)
    sensor_type = Column(String, index=True, nullable=False)
    # Natural identity is additive and nullable for historical rows.  New
    # writers use it for MQTT redelivery/commit-unknown deduplication.
    ingest_id = Column(String(64), nullable=True)
    
    data = Column(JSON, nullable=False)
    
    value_1 = Column(Float, nullable=True) 
    value_2 = Column(Float, nullable=True)  
    value_3 = Column(Float, nullable=True)  
    value_4 = Column(Float, nullable=True)  
    value_5 = Column(Float, nullable=True)  

class LatestSensorCache(BaseData):
    """Bảng cache giá trị sensor mới nhất — upsert mỗi lần MQTT nhận data,
    không phụ thuộc chu kỳ lưu sensor_data. Dùng để frontend luôn hiện số mới nhất."""
    __tablename__ = "latest_sensor_cache"
    __table_args__ = (
        Index('ix_latest_cache_station_sensor', 'station_id', 'sensor_type', unique=True),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    station_id = Column(Integer, nullable=False)
    sensor_type = Column(String, nullable=False)
    timestamp = Column(BigInteger, nullable=False)
    data = Column(JSON, nullable=False)


class Alert(BaseData):
    __tablename__ = "alerts"
    __table_args__ = (
        Index(
            "ix_alerts_station_unresolved_ts",
            "station_id",
            "is_resolved",
            "timestamp",
        ),
    )
    
    id = Column(Integer, primary_key=True)
    station_id = Column(Integer, index=True, nullable=False)
    timestamp = Column(BigInteger, nullable=False)
    level = Column(String, nullable=False)  # CRITICAL, WARNING, INFO
    category = Column(String, nullable=False)  # GNSS, RAIN, WATER, IMU
    message = Column(String, nullable=False)
    is_resolved = Column(Boolean, default=False, nullable=False)


class GnssDailySummary(BaseData):
    __tablename__ = "gnss_daily_summary"
    __table_args__ = (
        Index('ix_gnss_daily_station_day', 'station_id', 'day_start_ts', unique=True),
        Index('ix_gnss_daily_day', 'day_start_ts'),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    station_id = Column(Integer, index=True, nullable=False)
    day_start_ts = Column(BigInteger, nullable=False)  # UTC 00:00:00
    day_end_ts = Column(BigInteger, nullable=False)    # UTC 00:00:00 ngày kế tiếp

    sample_count = Column(Integer, default=0, nullable=False)
    first_ts = Column(BigInteger, nullable=True)
    last_ts = Column(BigInteger, nullable=True)
    duration_seconds = Column(BigInteger, default=0, nullable=False)

    net_displacement_mm = Column(Float, default=0.0, nullable=False)
    velocity_mm_day = Column(Float, default=0.0, nullable=False)
    velocity_mm_second = Column(Float, default=0.0, nullable=False)
    classification = Column(String, default="N/A", nullable=False)
    risk_level = Column(String, default="UNKNOWN", nullable=False)
    is_safe = Column(Boolean, default=True, nullable=False)
    status = Column(String, default="insufficient_data", nullable=False)
    message = Column(String, default="", nullable=False)

    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)


class GnssWeeklySummary(BaseData):
    __tablename__ = "gnss_weekly_summary"
    __table_args__ = (
        Index('ix_gnss_weekly_station_range', 'station_id', 'week_start_ts', 'week_end_ts', unique=True),
        Index('ix_gnss_weekly_end', 'week_end_ts'),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    station_id = Column(Integer, index=True, nullable=False)
    week_start_ts = Column(BigInteger, nullable=False)
    week_end_ts = Column(BigInteger, nullable=False)

    day_count = Column(Integer, default=0, nullable=False)
    total_displacement_mm = Column(Float, default=0.0, nullable=False)
    avg_velocity_mm_day = Column(Float, default=0.0, nullable=False)
    max_velocity_mm_day = Column(Float, default=0.0, nullable=False)
    min_velocity_mm_day = Column(Float, default=0.0, nullable=False)
    classification = Column(String, default="N/A", nullable=False)
    risk_level = Column(String, default="UNKNOWN", nullable=False)
    is_safe = Column(Boolean, default=True, nullable=False)
    status = Column(String, default="insufficient_data", nullable=False)
    message = Column(String, default="", nullable=False)

    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)


class RescueRequest(BaseData):
    __tablename__ = "rescue_requests"
    __table_args__ = (
        Index('ix_rescue_requests_status_created', 'status', 'created_at'),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    created_at = Column(BigInteger, nullable=False, index=True)
    requester_name = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    message = Column(String, nullable=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    accuracy_m = Column(Float, nullable=True)
    status = Column(String, nullable=False, default='pending')  # pending/resolved/rejected
    admin_note = Column(String, nullable=True)
    handled_by = Column(String, nullable=True)
    handled_at = Column(BigInteger, nullable=True)


class IncidentCase(BaseData):
    """Durable, non-PII operations case built from an Alert or RescueRequest."""

    __tablename__ = "incident_cases"
    __table_args__ = (
        UniqueConstraint("source_kind", "source_id", name="uq_incident_source"),
        Index("ix_incident_attention", "status", "priority", "updated_at", "id"),
        Index("ix_incident_scope_status", "project_id", "status", "updated_at", "id"),
        Index("ix_incident_station_status", "station_id", "status", "updated_at", "id"),
        Index("ix_incident_signal", "source_severity", "signal_state", "updated_at", "id"),
        Index("ix_incident_lookup_pending", "updated_at", "id", postgresql_where=text("scope_state = 'LOOKUP_PENDING'")),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    reference = Column(String(40), nullable=False, unique=True, index=True)
    source_kind = Column(String(24), nullable=False)
    source_id = Column(BigInteger, nullable=False)
    project_id = Column(Integer, nullable=True, index=True)
    station_id = Column(Integer, nullable=True, index=True)
    scope_state = Column(String(20), nullable=False, default="LOOKUP_PENDING")
    project_name_snapshot = Column(String(255), nullable=True)
    project_code_snapshot = Column(String(100), nullable=True)
    station_name_snapshot = Column(String(255), nullable=True)
    station_code_snapshot = Column(String(100), nullable=True)
    title = Column(String(255), nullable=False)
    summary = Column(Text, nullable=False, default="")
    source_severity = Column(String(16), nullable=False, default="UNKNOWN")
    signal_state = Column(String(16), nullable=False, default="UNKNOWN")
    priority = Column(String(16), nullable=False, default="UNTRIAGED")
    status = Column(String(24), nullable=False, default="new")
    assigned_to_user_id = Column(Integer, nullable=True, index=True)
    assigned_to_username = Column(String(150), nullable=True)
    opened_at = Column(BigInteger, nullable=False)
    last_signal_at = Column(BigInteger, nullable=False)
    acknowledged_at = Column(BigInteger, nullable=True)
    resolved_at = Column(BigInteger, nullable=True)
    updated_at = Column(BigInteger, nullable=False)
    version = Column(Integer, nullable=False, default=1)
    revision = Column(BigInteger, nullable=False, default=1)
    last_event_sequence = Column(Integer, nullable=False, default=0)


class IncidentEvent(BaseData):
    """Append-only, non-PII case timeline event."""

    __tablename__ = "incident_events"
    __table_args__ = (
        UniqueConstraint("incident_id", "sequence", name="uq_incident_event_sequence"),
        Index("ix_incident_events_case_created", "incident_id", "created_at", "id"),
        Index("ix_incident_events_project_cursor", "project_id_at_event", "id"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    incident_id = Column(BigInteger, nullable=False, index=True)
    sequence = Column(Integer, nullable=False)
    event_type = Column(String(32), nullable=False)
    actor_kind = Column(String(16), nullable=False, default="system")
    actor_user_id = Column(Integer, nullable=True)
    actor_username = Column(String(150), nullable=True)
    project_id_at_event = Column(Integer, nullable=True)
    previous_project_id = Column(Integer, nullable=True)
    created_at = Column(BigInteger, nullable=False)
    note = Column(Text, nullable=True)
    payload = Column(JSON, nullable=False, default=dict)
    mutation_request_id = Column(BigInteger, nullable=True)


class IncidentMutationRequest(BaseData):
    """Idempotency ledger for authenticated Incident mutations."""

    __tablename__ = "incident_mutation_requests"
    __table_args__ = (
        UniqueConstraint("incident_id", "actor_user_id", "idempotency_key", name="uq_incident_mutation_key"),
        Index("ix_incident_mutation_incident", "incident_id", "created_at"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    incident_id = Column(BigInteger, nullable=False, index=True)
    actor_user_id = Column(Integer, nullable=False)
    idempotency_key = Column(String(64), nullable=False)
    action = Column(String(48), nullable=False)
    request_fingerprint = Column(String(64), nullable=False)
    sequence_from = Column(Integer, nullable=True)
    sequence_to = Column(Integer, nullable=True)
    result_revision = Column(BigInteger, nullable=True)
    result_version = Column(Integer, nullable=True)
    changed = Column(Boolean, nullable=False, default=False)
    created_at = Column(BigInteger, nullable=False)


class FileCleanupJob(BaseData):
    """Small durable outbox placeholder for rescue upload cleanup."""

    __tablename__ = "file_cleanup_jobs"
    __table_args__ = (
        UniqueConstraint("upload_id", "job_generation", name="uq_cleanup_upload_generation"),
        Index("ix_cleanup_status_run_after", "status", "run_after"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    upload_id = Column(String(36), nullable=False)
    image_storage_key = Column(String(255), nullable=True)
    job_generation = Column(Integer, nullable=False, default=0)
    status = Column(String(16), nullable=False, default="PENDING")
    attempts = Column(Integer, nullable=False, default=0)
    run_after = Column(BigInteger, nullable=False)
    lease_owner = Column(String(64), nullable=True)
    lease_until = Column(BigInteger, nullable=True)
    lease_generation = Column(Integer, nullable=False, default=0)
    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)
    last_error_code = Column(String(64), nullable=True)


class SimulationRun(BaseData):
    """Auditable, reproducible result of one landslide scenario."""

    __tablename__ = "simulation_runs"
    __table_args__ = (
        Index("ix_simulation_runs_project_created", "project_id", "created_at"),
        Index("ix_simulation_runs_station_created", "station_id", "created_at"),
        Index("ix_simulation_runs_status_created", "status", "created_at"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    display_name = Column(String(240), nullable=False)
    created_by_user_id = Column(Integer, nullable=False, index=True)
    created_by_username = Column(String(150), nullable=False)
    project_id = Column(Integer, nullable=True)
    project_code = Column(String(80), nullable=True)
    project_name = Column(String(255), nullable=True)
    station_id = Column(Integer, nullable=True)
    station_code = Column(String(80), nullable=True)
    station_name = Column(String(255), nullable=True)
    mode = Column(String(32), nullable=False)
    status = Column(String(24), nullable=False, default="queued")
    progress = Column(Integer, nullable=False, default=0)
    engine_version = Column(String(32), nullable=False)
    schema_version = Column(Integer, nullable=False, default=1)
    seed = Column(BigInteger, nullable=False)
    sim_duration_seconds = Column(Integer, nullable=False)
    parameters = Column(JSON, nullable=False)
    parameter_sources = Column(JSON, nullable=False, default=dict)
    sensor_snapshot = Column(JSON, nullable=False, default=dict)
    time_series = Column(JSON, nullable=False, default=list)
    events = Column(JSON, nullable=False, default=list)
    summary = Column(JSON, nullable=False, default=dict)
    terrain_profile = Column(JSON, nullable=False, default=list)
    warnings = Column(JSON, nullable=False, default=list)
    error_detail = Column(Text, nullable=True)
    created_at = Column(BigInteger, nullable=False)
    started_at = Column(BigInteger, nullable=True)
    finished_at = Column(BigInteger, nullable=True)
    updated_at = Column(BigInteger, nullable=False)
