from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class User(Base):
    __tablename__ = 'users'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    role: Mapped[str] = mapped_column(String(32), default='administrator')
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    sessions: Mapped[list['Session']] = relationship(back_populates='user', cascade='all, delete-orphan')


class Session(Base):
    __tablename__ = 'sessions'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    csrf_token: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped['User'] = relationship(back_populates='sessions')


class MetricSample(Base):
    __tablename__ = 'metric_samples'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True, default=datetime.utcnow)

    cpu_percent: Mapped[float] = mapped_column(Float)
    memory_percent: Mapped[float] = mapped_column(Float)
    temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)


class DiskSample(Base):
    __tablename__ = 'disk_samples'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    metric_sample_id: Mapped[int] = mapped_column(ForeignKey('metric_samples.id', ondelete='CASCADE'), index=True)
    mountpoint: Mapped[str] = mapped_column(String(256))
    used_percent: Mapped[float] = mapped_column(Float)
    total_bytes: Mapped[int] = mapped_column(Integer)
    used_bytes: Mapped[int] = mapped_column(Integer)


class AuditLog(Base):
    __tablename__ = 'audit_logs'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True, default=datetime.utcnow)
    username: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(128), index=True)
    details: Mapped[str] = mapped_column(Text)
    remote_ip: Mapped[str | None] = mapped_column(String(128), nullable=True)


class LogBundle(Base):
    __tablename__ = 'log_bundles'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bundle_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    filename: Mapped[str] = mapped_column(String(256))
    file_path: Mapped[str] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_by: Mapped[str] = mapped_column(String(64))
