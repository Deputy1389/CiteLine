"""
SQLAlchemy database engine and session management.
"""
from __future__ import annotations

import os
import logging
import re
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from dotenv import load_dotenv

logger = logging.getLogger("linecite.db")

def get_database_url() -> str:
    load_dotenv()
    url = os.environ.get("DATABASE_URL")
    if url:
        url = url.strip()
    
    if not url:
        url = "sqlite:///C:/Citeline/data/citeline.db"
    
    # Render provides postgres:// but SQLAlchemy 2.0 requires postgresql://
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
        
    # AUTO-FIX: Force Supabase IPv4 Pooler for Render (IPv6 workaround)
    # Target host: db.oqvemwshlhikhodlrjjk.supabase.co
    if "oqvemwshlhikhodlrjjk" in url and "pooler.supabase.com" not in url:
        logger.info("Auto-patching Supabase URL for IPv4 Pooler compatibility...")
        
        # 1. Switch host and port
        url = url.replace("db.oqvemwshlhikhodlrjjk.supabase.co", "aws-0-us-west-1.pooler.supabase.com")
        url = url.replace(":5432", ":6543")
        
        # 2. Fix username (must be postgres.[PROJECT_REF])
        # We target the 'postgres' user specifically between '://' and the password separator ':' or '@'
        url = re.sub(r"://postgres([:@])", r"://postgres.oqvemwshlhikhodlrjjk\1", url)
        
        # 3. Ensure SSL
        if "sslmode=" not in url:
            sep = "&" if "?" in url else "?"
            url += f"{sep}sslmode=require"
            
    return url

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
    """Apply lightweight schema fixes."""
    url = get_database_url()
    if url.startswith("sqlite"):
        return
    
    try:
        engine = get_engine()
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE artifacts ALTER COLUMN artifact_type TYPE VARCHAR(64)"))
            conn.execute(text("ALTER TABLE runs ADD COLUMN IF NOT EXISTS retry_count INTEGER DEFAULT 0"))
    except Exception:
        pass

@contextmanager
def get_session() -> Generator[Session, None, None]:
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
