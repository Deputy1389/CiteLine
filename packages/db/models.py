"""
SQLAlchemy ORM models for CiteLine persistence.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone as dt_timezone

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, JSON
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
    status = Column(String(50), default="trial")  # trial | paid | churned
    tier = Column(String(50), default="starter")   # starter | pro | enterprise
    created_at = Column(DateTime, default=utcnow)
    
    matters = relationship("Matter", back_populates="firm", cascade="all, delete-orphan")
    sales_events = relationship("SalesEvent", back_populates="firm", cascade="all, delete-orphan")
    webhook_endpoints = relationship("WebhookEndpoint", back_populates="firm", cascade="all, delete-orphan")


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
    status = Column(String(20), default="pending")  # pending | running | success | partial | failed | needs_review
    created_at = Column(DateTime, default=utcnow)
    config_json = Column(JSON, nullable=True)
    metrics_json = Column(JSON, nullable=True)
    warnings_json = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    processing_seconds = Column(Float, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    provenance_json = Column(JSON, nullable=True)
    invariant_attestation_json = Column(JSON, nullable=True)  # Pass 37: InvariantGuard attestation
    retry_count = Column(Integer, default=0)
    
    # Worker management
    claimed_at = Column(DateTime, nullable=True)
    worker_id = Column(String(100), nullable=True)
    heartbeat_at = Column(DateTime, nullable=True)

    # Pass 043: Queue / idempotency columns (all nullable — backward-compatible)
    idempotency_key = Column(String(64), nullable=True, unique=True, index=True)  # sha256 hex of (firm_id|packet_sha256|export_mode|policy_version|signal_layer_version)
    attempt = Column(Integer, default=0, nullable=False)   # increments on each retry of the same run_id
    lock_expires_at = Column(DateTime, nullable=True)       # heartbeat extends this; sweeper requeues when expired

    # Pass 042: Observability columns (all nullable — backward-compatible)
    signal_layer_version = Column(String(20), nullable=True)   # e.g. "v36"
    policy_version = Column(String(50), nullable=True)          # e.g. "LI_V1_2026-03-01"
    policy_fingerprint = Column(String(16), nullable=True)      # first 16 chars of sha256
    packet_page_count = Column(Integer, nullable=True)
    packet_bytes = Column(Integer, nullable=True)
    error_class = Column(String(50), nullable=True)             # RunErrorClass enum value
    
    matter = relationship("Matter", back_populates="runs")
    artifacts = relationship("Artifact", back_populates="run", cascade="all, delete-orphan")
    pages = relationship("Page", back_populates="run", cascade="all, delete-orphan")
    segments = relationship("DocumentSegment", back_populates="run", cascade="all, delete-orphan")
    providers = relationship("Provider", back_populates="run", cascade="all, delete-orphan")
    events = relationship("Event", back_populates="run", cascade="all, delete-orphan")
    citations = relationship("Citation", back_populates="run", cascade="all, delete-orphan")
    gaps = relationship("Gap", back_populates="run", cascade="all, delete-orphan")
    invariant_results = relationship("InvariantResult", back_populates="run", cascade="all, delete-orphan")
    run_metrics = relationship("RunMetric", back_populates="run", cascade="all, delete-orphan")


class InvariantResult(Base):
    """Pass 042: Persisted record of every invariant check result for a production run."""
    __tablename__ = "invariant_results"

    id = Column(String(120), primary_key=True, default=_uuid)
    run_id = Column(String(120), ForeignKey("runs.id"), nullable=False, index=True)
    check_name = Column(String(80), nullable=False)   # e.g. "CHECK-D3", "INV-E1"
    passed = Column(Boolean, nullable=False)
    outcome = Column(Text, nullable=True)              # short detail string from harness
    severity = Column(String(10), nullable=False)      # "info" | "warn" | "fail"
    created_at = Column(DateTime, default=utcnow)

    run = relationship("Run", back_populates="invariant_results")


class RunMetric(Base):
    """Pass 042: Per-stage timing and numeric metrics for a production run."""
    __tablename__ = "run_metrics"

    id = Column(String(120), primary_key=True, default=_uuid)
    run_id = Column(String(120), ForeignKey("runs.id"), nullable=False, index=True)
    metric_name = Column(String(80), nullable=False)    # e.g. "extract_time_ms"
    metric_value_num = Column(Float, nullable=True)
    metric_value_text = Column(String(200), nullable=True)
    created_at = Column(DateTime, default=utcnow)

    run = relationship("Run", back_populates="run_metrics")



class Artifact(Base):
    __tablename__ = "artifacts"

    id = Column(String(120), primary_key=True, default=_uuid)
    run_id = Column(String(120), ForeignKey("runs.id"), nullable=False)
    artifact_type = Column(String(64), nullable=False)  # evidence_graph | output_pdf | acceptance_check | etc.
    storage_uri = Column(String(500), nullable=False)
    sha256 = Column(String(64), nullable=False)
    bytes = Column(Integer, nullable=False)
    # Pass 043: Atomic write state gate (INV-Q1)
    write_state = Column(String(16), default="committed", nullable=False)  # "writing" | "committed"

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
    extensions_json = Column(JSON, nullable=True)

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


class OCRCache(Base):
    __tablename__ = "ocr_cache"

    id = Column(String(120), primary_key=True, default=_uuid)
    source_document_id = Column(String(120), ForeignKey("source_documents.id"), nullable=False)
    document_sha256 = Column(String(64), nullable=False)
    page_number = Column(Integer, nullable=False)
    text = Column(Text, nullable=True)
    text_hash = Column(String(64), nullable=True)
    ocr_engine = Column(String(50), nullable=True)
    dpi = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=utcnow)

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


class OpsEvent(Base):
    __tablename__ = "ops_events"

    id = Column(String(120), primary_key=True, default=_uuid)
    ts = Column(DateTime, default=utcnow)
    source = Column(String(50), nullable=False)  # api | worker | n8n | stripe
    stage = Column(String(100), nullable=False)  # demo_download | export | gate | email_send | scrape
    severity = Column(String(20), nullable=False)  # info | warn | error | critical
    fingerprint = Column(String(200), nullable=False, index=True)
    message = Column(Text, nullable=True)
    firm_id = Column(String(120), nullable=True, index=True)
    matter_id = Column(String(120), nullable=True)
    run_id = Column(String(120), nullable=True)
    payload_json = Column(JSON, nullable=True)
    error_json = Column(JSON, nullable=True)


class Incident(Base):
    __tablename__ = "incidents"

    id = Column(String(120), primary_key=True, default=_uuid)
    fingerprint = Column(String(200), nullable=False, unique=True, index=True)
    first_seen_at = Column(DateTime, default=utcnow)
    last_seen_at = Column(DateTime, default=utcnow)
    occurrence_count_24h = Column(Integer, default=1)
    severity = Column(String(20), default="error")
    status = Column(String(20), default="OPEN")  # OPEN | INVESTIGATING | FIXED | IGNORED
    impact_score = Column(Float, default=0.0)
    resolved_at = Column(DateTime, nullable=True)


class SalesEvent(Base):
    __tablename__ = "sales_events"

    id = Column(String(120), primary_key=True, default=_uuid)
    ts = Column(DateTime, default=utcnow)
    firm_id = Column(String(120), ForeignKey("firms.id"), nullable=True)
    lead_id = Column(String(120), nullable=True, index=True)
    firm_name = Column(String(200), nullable=True)
    domain = Column(String(200), nullable=True, index=True)
    email = Column(String(200), nullable=True)
    stage = Column(String(50), nullable=False)  # scraped | demo_run | email_sent | trial_started | converted_to_paid
    status = Column(String(20), nullable=False)  # success | failure
    run_id = Column(String(120), nullable=True)
    error_json = Column(JSON, nullable=True)
    
    firm = relationship("Firm", back_populates="sales_events")


class SystemConfig(Base):
    __tablename__ = "system_config"

    id = Column(String(120), primary_key=True, default=_uuid)
    key = Column(String(100), primary_key=True)  # outbound_paused | demo_success_threshold | etc
    value_json = Column(JSON, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class WebhookEndpoint(Base):
    __tablename__ = "webhook_endpoints"

    id = Column(String(120), primary_key=True, default=_uuid)
    firm_id = Column(String(120), ForeignKey("firms.id"), nullable=False, index=True)
    callback_url = Column(String(500), nullable=False)
    secret = Column(String(255), nullable=False)
    active = Column(Boolean, default=True, nullable=False)
    description = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    firm = relationship("Firm", back_populates="webhook_endpoints")
    events = relationship("WebhookEvent", back_populates="endpoint", cascade="all, delete-orphan")


class WebhookEvent(Base):
    __tablename__ = "webhook_events"

    id = Column(String(120), primary_key=True, default=_uuid)
    endpoint_id = Column(String(120), ForeignKey("webhook_endpoints.id"), nullable=False, index=True)
    event_type = Column(String(120), nullable=False)
    payload_json = Column(JSON, nullable=False)
    delivery_status = Column(String(32), default="pending", nullable=False)  # pending | delivered | failed
    attempt_count = Column(Integer, default=0, nullable=False)
    last_attempt_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    endpoint = relationship("WebhookEndpoint", back_populates="events")
