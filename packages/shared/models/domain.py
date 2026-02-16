from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field

from .enums import (
    DocumentType,
    EventType,
    FactKind,
    ImagingModality,
    PageType,
    ProviderType,
    RunStatus,
)
from .common import BBox, DateRange, EventDate


class Warning(BaseModel):
    code: str
    message: str
    page: Optional[int] = None
    document_id: Optional[str] = None


class RunConfig(BaseModel):
    """Configuration for a pipeline run."""
    ocr_enabled: bool = True
    ocr_language: str = "eng"
    max_pages: int = 1000
    pt_mode: object = "aggregate"  # aggregate or per_visit (Enum ideally)
    pt_aggregate_window_days: int = 7
    gap_threshold_days: int = 60
    event_confidence_min_export: int = 50
    low_confidence_event_behavior: object = "exclude"  # exclude or include_with_flag


class SourceDocument(BaseModel):
    document_id: str
    filename: str
    mime_type: str = "application/pdf"
    sha256: str
    bytes: int
    uploaded_at: Optional[datetime] = None
    page_count: Optional[int] = None


class Metrics(BaseModel):
    documents: int
    pages_total: int
    pages_ocr: int
    events_total: int
    events_exported: int
    providers_total: int
    pt_events_aggregated: Optional[int] = 0
    billing_events_total: Optional[int] = 0
    processing_seconds: Optional[float] = 0.0


class Provenance(BaseModel):
    pipeline_version: str = "0.1.0"
    extractor: dict = Field(default_factory=lambda: {"name": "citeline-deterministic", "version": "0.1.0"})
    ocr: dict = Field(default_factory=lambda: {"engine": "tesseract", "version": "5", "language": "en"})
    hashes: dict = Field(default_factory=lambda: {"inputs_sha256": "0" * 64, "outputs_sha256": "0" * 64})


class RunRecord(BaseModel):
    run_id: str
    started_at: datetime
    finished_at: datetime
    status: str
    warnings: list[Warning] = Field(default_factory=list)
    metrics: Metrics
    provenance: Provenance


class PageTypeSpan(BaseModel):
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    page_type: PageType


class Document(BaseModel):
    document_id: str
    source_document_id: str
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    page_types: list[PageTypeSpan] = Field(min_length=1)
    detected_title: Optional[str] = None
    declared_document_type: Optional[DocumentType] = None
    confidence: Optional[int] = None


class PageLayout(BaseModel):
    width: float
    height: float
    orientation: str = "portrait"


class Page(BaseModel):
    page_id: str
    source_document_id: str
    page_number: int = Field(ge=1)
    text: str
    text_source: str
    layout: Optional[PageLayout] = None
    page_type: Optional[PageType] = None


class ProviderEvidence(BaseModel):
    page_number: int = Field(ge=1)
    snippet: str = Field(max_length=260)
    bbox: BBox


class Provider(BaseModel):
    provider_id: str
    detected_name_raw: str = Field(max_length=200)
    normalized_name: str = Field(max_length=200)
    provider_type: ProviderType = ProviderType.UNKNOWN
    confidence: int = Field(ge=0, le=100)
    evidence: list[ProviderEvidence] = Field(default_factory=list)


class Fact(BaseModel):
    text: str = Field(min_length=1, max_length=400)
    kind: FactKind
    verbatim: bool
    citation_id: str
    confidence: Optional[int] = None


class ImagingDetails(BaseModel):
    modality: ImagingModality
    body_part: str = Field(max_length=80)
    impression: list[Fact] = Field(default_factory=list)


class BillingDetails(BaseModel):
    statement_date: date
    service_date_range: Optional[DateRange] = None
    total_amount: float = Field(ge=0)
    currency: str = "USD"
    line_item_count: Optional[int] = None
    has_cpt_codes: bool = False
    has_icd_codes: bool = False


class Citation(BaseModel):
    citation_id: str
    source_document_id: str
    page_number: int = Field(ge=1)
    snippet: str = Field(min_length=1, max_length=500)
    bbox: BBox
    text_hash: Optional[str] = None


class Gap(BaseModel):
    gap_id: str
    start_date: date
    end_date: date
    duration_days: int = Field(ge=0)
    threshold_days: int = Field(ge=1)
    confidence: int = Field(ge=0, le=100)
    related_event_ids: list[str] = Field(default_factory=list)


class SkippedEvent(BaseModel):
    """Debug record for events that were detected but not emitted."""
    page_numbers: list[int] = Field(min_length=1)
    reason_code: str  # MISSING_DATE, NO_FACTS, NO_TRIGGER_MATCH, etc.
    snippet: str = Field(max_length=300)


class Event(BaseModel):
    event_id: str
    provider_id: str
    event_type: EventType
    date: Optional[EventDate] = None
    encounter_type_raw: Optional[str] = None
    facts: list[Fact] = Field(min_length=1, max_length=30)
    diagnoses: list[Fact] = Field(default_factory=list)
    medications: list[Fact] = Field(default_factory=list)
    procedures: list[Fact] = Field(default_factory=list)
    imaging: Optional[ImagingDetails] = None
    billing: Optional[BillingDetails] = None
    confidence: int = Field(ge=0, le=100)
    flags: list[str] = Field(default_factory=list)
    citation_ids: list[str] = Field(min_length=1)
    source_page_numbers: list[int] = Field(min_length=1)


class EvidenceGraph(BaseModel):
    schema_version: str = "1.0"
    documents: list[Document] = Field(default_factory=list)
    pages: list[Page] = Field(default_factory=list)
    providers: list[Provider] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    gaps: list[Gap] = Field(default_factory=list)
    skipped_events: list[SkippedEvent] = Field(default_factory=list)
    extensions: dict = Field(default_factory=dict)


class ArtifactRef(BaseModel):
    uri: str = Field(min_length=1, max_length=500)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    bytes: int = Field(ge=1)


class ChronologyExports(BaseModel):
    pdf: ArtifactRef
    csv: ArtifactRef
    docx: Optional[ArtifactRef] = None
    json_export: Optional[ArtifactRef] = Field(default=None, alias="json")


class ChronologyOutput(BaseModel):
    export_format_version: str = "0.1.0"
    events_exported: list[str] = Field(default_factory=list)
    exports: ChronologyExports


class CaseInfo(BaseModel):
    case_id: str = Field(min_length=6, max_length=80)
    firm_id: str = Field(min_length=3, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    timezone: str = "America/Los_Angeles"
    client_ref: Optional[str] = None
    notes: Optional[str] = None


class PipelineInputs(BaseModel):
    source_documents: list[SourceDocument] = Field(min_length=1)
    run_config: RunConfig = Field(default_factory=RunConfig)


class PipelineOutputs(BaseModel):
    run: RunRecord
    evidence_graph: EvidenceGraph
    chronology: ChronologyOutput


class ChronologyResult(BaseModel):
    """Top-level output object matching the JSON schema."""
    schema_version: str = "0.1.0"
    generated_at: datetime
    case: CaseInfo
    inputs: PipelineInputs
    outputs: PipelineOutputs
