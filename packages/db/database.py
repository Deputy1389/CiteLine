"""
SQLAlchemy database engine and session management.
"""
from __future__ import annotations

import os
import logging
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger("linecite.db")

def get_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        # Fallback only for local development
        url = "sqlite:///C:/Citeline/data/citeline.db"
    
    # Render (and Heroku) provide postgres:// but SQLAlchemy 2.0 requires postgresql://
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
        
    # AUTO-FIX: Force Supabase IPv4 Pooler for Render
    # Render doesn't support IPv6, and Supabase Direct is IPv6-only.
    # We rewrite the host to the transaction pooler on port 6543.
    if "db.oqvemwshlhikhodlrjjk.supabase.co" in url:
        logger.info("Detected Supabase Direct URL. Switching to IPv4 Pooler for Render compatibility.")
        # Replace host and port
        url = url.replace("db.oqvemwshlhikhodlrjjk.supabase.co", "aws-0-us-west-1.pooler.supabase.com")
        url = url.replace(":5432", ":6543")
        # Ensure SSL is required
        if "?sslmode=require" not in url:
            url += "?sslmode=require"
            
    return url

# Lazy-loaded engine and session
_engine = None
_SessionLocal = None

def get_engine():
    global _engine
    if _engine is None:
        url = get_database_url()
        connect_args = {}
        if url.startswith("sqlite"):
            connect_args = {"check_same_thread": False}
        _engine = create_engine(url, echo=False, connect_args=connect_args)
    return _engine

def get_session_factory():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)
    return _SessionLocal

def init_db() -> None:
    """Create all tables (idempotent)."""
    from packages.db.models import Base
    Base.metadata.create_all(bind=get_engine())
    _apply_schema_migrations()

def _apply_schema_migrations() -> None:
    """Apply lightweight schema fixes for production without Alembic."""
    url = get_database_url()
    if url.startswith("sqlite"):
        return
    
    engine = get_engine()
    with engine.begin() as conn:
        try:
            conn.execute(text("ALTER TABLE artifacts ALTER COLUMN artifact_type TYPE VARCHAR(64)"))
        except Exception: pass
        try:
            conn.execute(text("ALTER TABLE runs ADD COLUMN IF NOT EXISTS retry_count INTEGER DEFAULT 0"))
        except Exception: pass

@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Context manager that yields a DB session."""
    factory = get_session_factory()
    session = factory()
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
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
