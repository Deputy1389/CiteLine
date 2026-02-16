"""
SQLAlchemy ORM models for CiteLine persistence.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone as dt_timezone

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text, JSON
from sqlalchemy.orm import DeclarativeBase, relationship

def _uuid():
    return uuid.uuid4().hex

def utcnow():
    return datetime.now(dt_timezone.utc)

class Base(DeclarativeBase):
    pass


class Firm(Base):
    __tablename__ = "firms"
    id = Column(String(120), primary_key=True, default=_uuid)
    name = Column(String(200), nullable=False)
    created_at = Column(DateTime, default=utcnow)
    
    matters = relationship("Matter", back_populates="firm", cascade="all, delete-orphan")


class Matter(Base):
    __tablename__ = "matters"
    id = Column(String(120), primary_key=True, default=_uuid)
    firm_id = Column(String(120), ForeignKey("firms.id"), nullable=False)
    title = Column(String(200), nullable=False)
    client_ref = Column(String(200), nullable=True)
    timezone = Column(String(50), default="America/Los_Angeles")
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    
    firm = relationship("Firm", back_populates="matters")
    runs = relationship("Run", back_populates="matter", cascade="all, delete-orphan")
    documents = relationship("SourceDocument", back_populates="matter", cascade="all, delete-orphan")


class SourceDocument(Base):
    __tablename__ = "source_documents"

    id = Column(String(120), primary_key=True, default=_uuid)
    matter_id = Column(String(120), ForeignKey("matters.id"), nullable=False)
    filename = Column(String(200), nullable=False)
    mime_type = Column(String(100), nullable=False)
    storage_uri = Column(String(500), nullable=True)
    sha256 = Column(String(64), nullable=False)
    bytes = Column(Integer, nullable=False)
    uploaded_at = Column(DateTime, default=utcnow)
    page_count = Column(Integer, nullable=True)

    matter = relationship("Matter", back_populates="documents")


class Run(Base):
    __tablename__ = "runs"

    id = Column(String(120), primary_key=True, default=_uuid)
    matter_id = Column(String(120), ForeignKey("matters.id"), nullable=False)
    status = Column(String(20), default="pending")  # pending | running | success | partial | failed
    created_at = Column(DateTime, default=utcnow)
    config_json = Column(JSON, nullable=True)
    metrics_json = Column(JSON, nullable=True)
    warnings_json = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    processing_seconds = Column(Float, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    provenance_json = Column(JSON, nullable=True)
    
    # Worker management
    claimed_at = Column(DateTime, nullable=True)
    worker_id = Column(String(100), nullable=True)
    heartbeat_at = Column(DateTime, nullable=True)
    
    matter = relationship("Matter", back_populates="runs")
    artifacts = relationship("Artifact", back_populates="run", cascade="all, delete-orphan")
    pages = relationship("Page", back_populates="run", cascade="all, delete-orphan")
    segments = relationship("DocumentSegment", back_populates="run", cascade="all, delete-orphan")
    providers = relationship("Provider", back_populates="run", cascade="all, delete-orphan")
    events = relationship("Event", back_populates="run", cascade="all, delete-orphan")
    citations = relationship("Citation", back_populates="run", cascade="all, delete-orphan")
    gaps = relationship("Gap", back_populates="run", cascade="all, delete-orphan")


class Artifact(Base):
    __tablename__ = "artifacts"

    id = Column(String(120), primary_key=True, default=_uuid)
    run_id = Column(String(120), ForeignKey("runs.id"), nullable=False)
    artifact_type = Column(String(20), nullable=False)  # pdf | csv | json
    storage_uri = Column(String(500), nullable=False)
    sha256 = Column(String(64), nullable=False)
    bytes = Column(Integer, nullable=False)

    run = relationship("Run", back_populates="artifacts")


class Page(Base):
    __tablename__ = "pages"

    id = Column(String(120), primary_key=True, default=_uuid)
    run_id = Column(String(120), ForeignKey("runs.id"), nullable=False)
    source_document_id = Column(String(120), ForeignKey("source_documents.id"), nullable=False)
    page_number = Column(Integer, nullable=False)
    text = Column(Text, nullable=True)
    text_source = Column(String(50), nullable=True)  # embedded_pdf_text | ocr
    page_type = Column(String(50), nullable=True)
    layout_json = Column(JSON, nullable=True)
    
    run = relationship("Run", back_populates="pages")
    source_document = relationship("SourceDocument")


class DocumentSegment(Base):
    __tablename__ = "document_segments"

    id = Column(String(120), primary_key=True, default=_uuid)
    run_id = Column(String(120), ForeignKey("runs.id"), nullable=False)
    source_document_id = Column(String(120), ForeignKey("source_documents.id"), nullable=False)
    page_start = Column(Integer, nullable=False)
    page_end = Column(Integer, nullable=False)
    page_types_json = Column(JSON, nullable=True)
    declared_document_type = Column(String(50), nullable=True)
    confidence = Column(Integer, nullable=True)

    run = relationship("Run", back_populates="segments")
    source_document = relationship("SourceDocument")


class Provider(Base):
    __tablename__ = "providers"

    id = Column(String(120), primary_key=True, default=_uuid)
    run_id = Column(String(120), ForeignKey("runs.id"), nullable=False)
    detected_name_raw = Column(String(200), nullable=True)
    normalized_name = Column(String(200), nullable=True)
    provider_type = Column(String(50), nullable=True)
    confidence = Column(Integer, nullable=True)
    evidence_json = Column(JSON, nullable=True)

    run = relationship("Run", back_populates="providers")
    events = relationship("Event", back_populates="provider")


class Event(Base):
    __tablename__ = "events"

    id = Column(String(120), primary_key=True, default=_uuid)
    run_id = Column(String(120), ForeignKey("runs.id"), nullable=False)
    provider_id = Column(String(120), ForeignKey("providers.id"), nullable=True)
    event_type = Column(String(50), nullable=False)
    date_json = Column(JSON, nullable=False)
    encounter_type_raw = Column(String(120), nullable=True)
    facts_json = Column(JSON, nullable=True)
    diagnoses_json = Column(JSON, nullable=True)
    procedures_json = Column(JSON, nullable=True)
    imaging_json = Column(JSON, nullable=True)
    billing_json = Column(JSON, nullable=True)
    confidence = Column(Integer, nullable=True)
    flags_json = Column(JSON, nullable=True)
    citation_ids_json = Column(JSON, nullable=True)
    source_page_numbers_json = Column(JSON, nullable=True)

    run = relationship("Run", back_populates="events")
    provider = relationship("Provider", back_populates="events")


class Citation(Base):
    __tablename__ = "citations"

    id = Column(String(120), primary_key=True, default=_uuid)
    run_id = Column(String(120), ForeignKey("runs.id"), nullable=False)
    source_document_id = Column(String(120), ForeignKey("source_documents.id"), nullable=False)
    page_number = Column(Integer, nullable=False)
    snippet = Column(Text, nullable=True)
    bbox_json = Column(JSON, nullable=True)
    text_hash = Column(String(64), nullable=True)

    run = relationship("Run", back_populates="citations")
    source_document = relationship("SourceDocument")


class Gap(Base):
    __tablename__ = "gaps"

    id = Column(String(120), primary_key=True, default=_uuid)
    run_id = Column(String(120), ForeignKey("runs.id"), nullable=False)
    start_date = Column(String(20), nullable=True)
    end_date = Column(String(20), nullable=True)
    duration_days = Column(Integer, nullable=True)
    threshold_days = Column(Integer, nullable=True)
    confidence = Column(Integer, nullable=True)
    related_event_ids_json = Column(JSON, nullable=True)

    run = relationship("Run", back_populates="gaps")
