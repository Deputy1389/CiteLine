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
    # If we see the direct Supabase host (which is IPv6-only), rewrite it to the pooler.
    if "supabase.co" in url and "pooler" not in url:
        # Extract project ref (e.g., oqvemwshlhikhodlrjjk)
        match = re.search(r"db\.([a-z0-9]+)\.supabase\.co", url)
        if match:
            project_ref = match.group(1)
            logger.info(f"Auto-patching Supabase URL for project {project_ref}...")
            
            # 1. Use the global pooler address (works for all regions)
            # We replace the host part entirely
            url = re.sub(r"@db\.[a-z0-9]+\.supabase\.co", f"@aws-0-us-west-1.pooler.supabase.com", url)
            
            # 2. Update port to 6543 (Pooler)
            url = url.replace(":5432", ":6543")
            
            # 3. Correct username format: postgres.[PROJECT_REF]
            # Precise regex to avoid double-patching or corrupting the protocol
            if f"postgres.{project_ref}" not in url:
                url = re.sub(r"://postgres([:@])", f"://postgres.{project_ref}\\1", url)
            
            # 4. Force SSL
            if "sslmode=" not in url:
                sep = "&" if "?" in url else "?"
                url += f"{sep}sslmode=require"
                
            # Log the patched host (hiding password)
            safe_url = re.sub(r"://([^:]+):([^@]+)@", r"://\1:****@", url)
            logger.info(f"Patched URL: {safe_url}")
            
    return url

_engine = None
_SessionLocal = None

def get_engine():
    global _engine
    if _engine is None:
        url = get_database_url()
        # Ensure we use psycopg 3 driver for PostgreSQL
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
            
        connect_args = {}
        if "sqlite" in url:
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
    if "sqlite" in url:
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
