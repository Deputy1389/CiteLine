"""
SQLAlchemy ORM models for CiteLine persistence.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, relationship


def _uuid() -> str:
    return uuid.uuid4().hex


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Firm(Base):
    __tablename__ = "firms"

    id = Column(String(80), primary_key=True, default=_uuid)
    name = Column(String(200), nullable=False)
    created_at = Column(DateTime, default=_utcnow)

    matters = relationship("Matter", back_populates="firm", cascade="all, delete-orphan")


class Matter(Base):
    __tablename__ = "matters"

    id = Column(String(80), primary_key=True, default=_uuid)
    firm_id = Column(String(80), ForeignKey("firms.id"), nullable=False)
    title = Column(String(200), nullable=False)
    timezone = Column(String(64), default="America/Los_Angeles")
    client_ref = Column(String(120), nullable=True)
    created_at = Column(DateTime, default=_utcnow)

    firm = relationship("Firm", back_populates="matters")
    source_documents = relationship("SourceDocument", back_populates="matter", cascade="all, delete-orphan")
    runs = relationship("Run", back_populates="matter", cascade="all, delete-orphan")


class SourceDocument(Base):
    __tablename__ = "source_documents"

    id = Column(String(120), primary_key=True, default=_uuid)
    matter_id = Column(String(80), ForeignKey("matters.id"), nullable=False)
    filename = Column(String(260), nullable=False)
    mime_type = Column(String(64), default="application/pdf")
    sha256 = Column(String(64), nullable=False)
    bytes = Column(Integer, nullable=False)
    storage_uri = Column(String(500), nullable=True)
    uploaded_at = Column(DateTime, default=_utcnow)

    matter = relationship("Matter", back_populates="source_documents")


class Run(Base):
    __tablename__ = "runs"

    id = Column(String(120), primary_key=True, default=_uuid)
    matter_id = Column(String(80), ForeignKey("matters.id"), nullable=False)
    status = Column(String(20), default="pending")  # pending | running | success | partial | failed
    config_json = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    metrics_json = Column(Text, nullable=True)
    warnings_json = Column(Text, nullable=True)
    provenance_json = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    processing_seconds = Column(Float, nullable=True)

    matter = relationship("Matter", back_populates="runs")
    artifacts = relationship("Artifact", back_populates="run", cascade="all, delete-orphan")


class Artifact(Base):
    __tablename__ = "artifacts"

    id = Column(String(120), primary_key=True, default=_uuid)
    run_id = Column(String(120), ForeignKey("runs.id"), nullable=False)
    artifact_type = Column(String(20), nullable=False)  # pdf | csv | json
    storage_uri = Column(String(500), nullable=False)
    sha256 = Column(String(64), nullable=False)
    bytes = Column(Integer, nullable=False)

    run = relationship("Run", back_populates="artifacts")
