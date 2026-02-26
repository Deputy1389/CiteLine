from datetime import date, datetime
from typing import Optional, Literal

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
    pt_mode: object = "aggregate"  # per_visit (one event/page) or aggregate (bucket by window)
    pt_aggregate_window_days: int = 7
    gap_threshold_days: int = 60
    event_confidence_min_export: int = 30  # Lowered from 40 to capture undated specialist events
    low_confidence_event_behavior: object = "exclude_from_export"  # exclude_from_export or include_with_flag
    enable_llm_reasoning: bool = True  # Enable Gemini Flash semantic reasoning (Step 19)
    gemini_model: str = "gemini-2.0-flash"  # Gemini model for LLM reasoning
    gemini_model_narrative: Optional[str] = None  # Optional override for narrative model
    llm_reasoning_min_confidence: int = 30
    llm_reasoning_min_citations: int = 1
    llm_reasoning_max_events: int = 50
    narrative_min_confidence: int = 30
    narrative_min_citations: int = 1
    narrative_max_events: int = 100
    clinical_max_facts: int = 12
    pt_max_facts: int = 4
    chronology_dedupe_facts_max: int = 3
    chronology_timeline_facts_max: int = 6
    chronology_merged_facts_max: int = 4
    chronology_appendix_facts_max: int = 10
    chronology_min_score: int = 60
    chronology_selection_hard_max_rows: int = 250
    litigation_defense_paths_limit: int = 6
    litigation_objection_profiles_limit: int = 24
    litigation_upgrade_recommendations_limit: int = 8
    litigation_quote_lock_limit: int = 12
    litigation_contradiction_limit: int = 24
    high_stakes_confidence_cap: int = 40
    api_download_timeout_seconds: int = 60
    error_message_max_len: int = 2000
    imaging_base_confidence: int = 20
    billing_base_confidence: int = 0
    lab_base_confidence: int = 60
    discharge_base_confidence: int = 75
    operative_base_confidence: int = 80
    confidence_scoring: dict[str, int] = Field(default_factory=lambda: {
        "date_explicit": 35,
        "date_range": 25,
        "date_propagated": 15,
        "date_ambiguous": 10,
        "date_undated": -50,
        "provider_bonus": 20,
        "strong_type_bonus": 15,
        "anchor_per": 7,
        "anchor_max": 21,
        "clinical_per": 4,
        "clinical_max": 12,
        "fact_richness_min": 3,
        "fact_richness_bonus": 8,
        "citation_bonus_2": 10,
        "citation_bonus_4": 5,
        "multi_page_bonus": 5,
        "time_bonus": 25,
    })


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
    extensions: dict = Field(default_factory=dict)


class Patient(BaseModel):
    name: Optional[str] = None
    mrn: Optional[str] = None
    sex: Optional[str] = None
    age: Optional[int] = None
    dob: Optional[date] = None
    sex_confidence: int = Field(default=0, ge=0, le=100)
    evidence_citation_ids: list[str] = Field(default_factory=list)


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
    text: str = Field(min_length=1, max_length=2000)
    kind: FactKind
    verbatim: bool
    citation_id: Optional[str] = None # Deprecating but keeping for compat
    citation_ids: list[str] = Field(default_factory=list)
    confidence: Optional[int] = None
    # OCR / text quality quarantine flag.
    # True = fact text failed quality checks (word-salad, low medical density, etc.).
    # Quarantined facts are EXCLUDED from attorney-facing PDF output but RETAINED in the
    # raw evidence graph for audit. Never deleted, never silently rewritten.
    technical_noise: bool = False


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


class NarrativeEntry(BaseModel):
    """A claim-anchored chronology row produced by the Composer LLM."""
    row_id: str
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    label: str = Field(default="General", description="Short phase label e.g. 'Acute Care', 'Imaging'")
    headline: str = Field(default="", max_length=300, description="One sentence summary of the claim unit")
    bullets: list[str] = Field(default_factory=list, max_length=5, description="Short supporting points")
    event_ids: list[str] = Field(default_factory=list, description="Strictly required source event IDs")
    citation_ids: list[str] = Field(default_factory=list, description="Computed union of source citations")
    tags: list[str] = Field(default_factory=list, description="e.g. 'imaging', 'surgery', 'gap', 'preexisting'")
    risk_flags: list[str] = Field(default_factory=list, description="e.g. 'gap_in_care', 'contradiction'")
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    exportable: bool = True 


class NarrativeChronology(BaseModel):
    """The collection of anchored narrative entries."""
    generated_at: datetime
    entries: list[NarrativeEntry] = Field(default_factory=list)
    model_name: Optional[str] = None


class RendererCitationValue(BaseModel):
    value: Optional[str] = None
    citation_ids: list[str] = Field(default_factory=list)


class RendererDoiField(RendererCitationValue):
    source: Literal["explicit", "inferred", "not_found"] = "not_found"


class RendererPtSummary(BaseModel):
    total_encounters: Optional[int] = None
    encounter_count_min: Optional[int] = None
    encounter_count_max: Optional[int] = None
    date_start: Optional[str] = None
    date_end: Optional[str] = None
    discharge_status: Optional[str] = None
    reconciliation_note: Optional[str] = None
    citation_ids: list[str] = Field(default_factory=list)
    count_source: Literal["structured", "aggregate_snippet", "event_count", "not_found"] = "not_found"


class PromotedFinding(BaseModel):
    category: Literal["objective_deficit", "imaging", "diagnosis", "procedure", "treatment", "visit_count", "symptom"]
    label: str = Field(min_length=1, max_length=500)
    body_region: Optional[str] = Field(default=None, max_length=80)
    severity: Optional[Literal["high", "medium", "low"]] = None
    headline_eligible: bool = True
    finding_polarity: Optional[Literal["positive", "negative", "neutral"]] = None
    citation_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source_event_id: Optional[str] = None
    semantic_family: Optional[str] = None
    finding_source_count: Optional[int] = None
    source_families: list[str] = Field(default_factory=list)


class RendererManifest(BaseModel):
    manifest_version: str = "1.0"
    doi: RendererDoiField = Field(default_factory=RendererDoiField)
    mechanism: RendererCitationValue = Field(default_factory=RendererCitationValue)
    pt_summary: RendererPtSummary = Field(default_factory=RendererPtSummary)
    promoted_findings: list[PromotedFinding] = Field(default_factory=list)
    top_case_drivers: list[str] = Field(default_factory=list)
    billing_completeness: Literal["complete", "partial", "none"] = "none"


class Event(BaseModel):
    event_id: str
    provider_id: Optional[str] = None
    event_type: EventType
    date: Optional[EventDate] = None
    encounter_type_raw: Optional[str] = None
    reason_for_visit: Optional[str] = None
    chief_complaint: Optional[str] = None
    author_name: Optional[str] = None
    author_role: Optional[str] = None
    facts: list[Fact] = Field(default_factory=list, max_length=100)
    diagnoses: list[Fact] = Field(default_factory=list)
    medications: list[Fact] = Field(default_factory=list)
    procedures: list[Fact] = Field(default_factory=list)
    exam_findings: list[Fact] = Field(default_factory=list)
    treatment_plan: list[Fact] = Field(default_factory=list)
    coding: dict[str, list[str]] = Field(default_factory=dict) # e.g. {"icd10": ["Z87.09"], "snomed": ["268565007"]}
    imaging: Optional[ImagingDetails] = None
    billing: Optional[BillingDetails] = None
    confidence: int = Field(ge=0, le=100)
    flags: list[str] = Field(default_factory=list)
    citation_ids: list[str] = Field(default_factory=list)
    source_page_numbers: list[int] = Field(default_factory=list)
    extensions: dict = Field(default_factory=dict)


class EvidenceGraph(BaseModel):
    schema_version: str = "1.0"
    documents: list[Document] = Field(default_factory=list)
    pages: list[Page] = Field(default_factory=list)
    providers: list[Provider] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    gaps: list[Gap] = Field(default_factory=list)
    skipped_events: list[SkippedEvent] = Field(default_factory=list)
    narrative_chronology: Optional[NarrativeChronology] = None
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
    summary: Optional[str] = None
    narrative_synthesis: Optional[str] = None
    events_exported: list[str] = Field(default_factory=list)
    exports: ChronologyExports


class CaseInfo(BaseModel):
    case_id: str = Field(min_length=6, max_length=80)
    firm_id: str = Field(min_length=3, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    timezone: str = "America/Los_Angeles"
    client_ref: Optional[str] = None
    patient: Optional[Patient] = None
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
