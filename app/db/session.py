"""
Database engine and session utilities.
"""
from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# Use a local sqlite DB by default for development. Deployments (e.g. the
# KVM Docker container) override this with GOALOS_DATABASE_URL so data
# persists on a mounted volume.
DATABASE_URL = os.getenv("GOALOS_DATABASE_URL", "sqlite:///./goalos.db")

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
