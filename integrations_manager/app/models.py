"""SQLAlchemy database models for the Integrations Manager.

Tables:
  - integrations: registered integration definitions
  - credentials: encrypted credential payloads per integration
  - oauth_tokens: OAuth access/refresh tokens per integration
  - connection_status: current connection state per integration
  - audit_logs: immutable log of all credential operations
"""
from __future__ import annotations

import datetime as _dt
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker


class Base(DeclarativeBase):
    pass


# ── Integrations ─────────────────────────────────────────────────────────
class Integration(Base):
    __tablename__ = "integrations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    slug = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(128), nullable=False)
    description = Column(Text, default="")
    icon = Column(String(128), default="")
    auth_type = Column(String(32), nullable=False)  # api_key | oauth2
    is_enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_dt.datetime.utcnow)
    updated_at = Column(DateTime, default=_dt.datetime.utcnow, onupdate=_dt.datetime.utcnow)

    credentials = relationship("Credential", back_populates="integration", cascade="all, delete-orphan")
    oauth_tokens = relationship("OAuthToken", back_populates="integration", cascade="all, delete-orphan")
    connection = relationship("ConnectionStatus", back_populates="integration", uselist=False, cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="integration", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Integration {self.slug!r}>"


# ── Credentials (encrypted payload) ─────────────────────────────────────
class Credential(Base):
    __tablename__ = "credentials"
    __table_args__ = (
        UniqueConstraint("integration_id", "credential_key", name="uq_cred_integration_key"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    integration_id = Column(Integer, ForeignKey("integrations.id"), nullable=False)
    credential_key = Column(String(128), nullable=False)
    encrypted_value = Column(Text, nullable=False)  # AES-256-GCM ciphertext (base64)
    is_secret = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_dt.datetime.utcnow)
    updated_at = Column(DateTime, default=_dt.datetime.utcnow, onupdate=_dt.datetime.utcnow)

    integration = relationship("Integration", back_populates="credentials")

    def __repr__(self) -> str:
        return f"<Credential {self.credential_key!r} integration={self.integration_id}>"


# ── OAuth tokens ─────────────────────────────────────────────────────────
class OAuthToken(Base):
    __tablename__ = "oauth_tokens"
    __table_args__ = (
        UniqueConstraint("integration_id", "provider", name="uq_oauth_integration_provider"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    integration_id = Column(Integer, ForeignKey("integrations.id"), nullable=False)
    provider = Column(String(64), nullable=False)
    encrypted_access_token = Column(Text, nullable=False)
    encrypted_refresh_token = Column(Text, nullable=True)
    token_type = Column(String(32), default="Bearer")
    expires_at = Column(DateTime, nullable=True)
    scopes = Column(Text, default="")
    created_at = Column(DateTime, default=_dt.datetime.utcnow)
    updated_at = Column(DateTime, default=_dt.datetime.utcnow, onupdate=_dt.datetime.utcnow)

    integration = relationship("Integration", back_populates="oauth_tokens")


# ── Connection status ───────────────────────────────────────────────────
class ConnectionStatus(Base):
    __tablename__ = "connection_status"

    id = Column(Integer, primary_key=True, autoincrement=True)
    integration_id = Column(Integer, ForeignKey("integrations.id"), unique=True, nullable=False)
    status = Column(String(32), default="not_configured")  # not_configured | configured | connected | error
    last_connected_at = Column(DateTime, nullable=True)
    last_tested_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_dt.datetime.utcnow)
    updated_at = Column(DateTime, default=_dt.datetime.utcnow, onupdate=_dt.datetime.utcnow)

    integration = relationship("Integration", back_populates="connection")


# ── Audit logs ──────────────────────────────────────────────────────────
class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    integration_id = Column(Integer, ForeignKey("integrations.id"), nullable=True)
    action = Column(String(64), nullable=False)
    actor = Column(String(128), default="admin")
    details = Column(Text, default="")
    ip_address = Column(String(45), default="")
    created_at = Column(DateTime, default=_dt.datetime.utcnow)

    integration = relationship("Integration", back_populates="audit_logs")


# ── Database engine ──────────────────────────────────────────────────────

def create_db_engine(database_url: str):
    """Create a SQLAlchemy engine with SQLite WAL mode."""
    connect_args = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    engine = create_engine(database_url, connect_args=connect_args, echo=False)
    # Enable WAL for SQLite
    if database_url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, _connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    return engine


def init_db(engine):
    """Create all tables if they don't exist."""
    Base.metadata.create_all(bind=engine)


def get_session_factory(engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)
