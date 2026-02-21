"""
SQLAlchemy database engine and session management.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///C:/Citeline/data/citeline.db")

# Render (and Heroku) provide postgres:// but SQLAlchemy 2.0 requires postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Connection arguments for SQLite (not needed for Postgres)
connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, echo=False, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    """Create all tables (idempotent)."""
    from packages.db.models import Base  # noqa: F811
    Base.metadata.create_all(bind=engine)
    _apply_schema_migrations()


def _apply_schema_migrations() -> None:
    """Apply lightweight schema fixes for production without Alembic."""
    if DATABASE_URL.startswith("sqlite"):
        return
    with engine.begin() as conn:
        try:
            conn.execute(
                text("ALTER TABLE artifacts ALTER COLUMN artifact_type TYPE VARCHAR(64)")
            )
        except Exception:
            # Likely already migrated or insufficient privileges; ignore to keep startup resilient.
            pass


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Context manager that yields a DB session and handles commit/rollback."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a DB session."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
