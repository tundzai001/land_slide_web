"""Operational records stored with the PostgreSQL data database."""

from sqlalchemy import BigInteger, Column, Index, Integer, JSON, String, Text

from app.database import BaseData


class _LogColumns:
    id = Column(BigInteger().with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    timestamp = Column(BigInteger, nullable=False)
    username = Column(String(150), nullable=True)
    role = Column(String(32), nullable=True)
    action = Column(String(255), nullable=False)
    object = Column(String(500), nullable=True)
    ip = Column(String(64), nullable=True)
    status = Column(Integer, nullable=True)
    details = Column(JSON, nullable=False, default=dict)


class AuditLog(_LogColumns, BaseData):
    __tablename__ = 'audit_log'
    __table_args__ = (
        Index('ix_audit_log_timestamp_id', 'timestamp', 'id'),
        Index('ix_audit_log_username_timestamp', 'username', 'timestamp'),
    )


class OperationLog(_LogColumns, BaseData):
    __tablename__ = 'operation_log'
    __table_args__ = (
        Index('ix_operation_log_timestamp_id', 'timestamp', 'id'),
        Index('ix_operation_log_username_timestamp', 'username', 'timestamp'),
    )


class OperationsSetting(BaseData):
    __tablename__ = 'operations_settings'

    key = Column(String(200), primary_key=True)
    value = Column(JSON, nullable=False)
