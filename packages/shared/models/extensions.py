from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class MissingRecordsGap(BaseModel):
    model_config = ConfigDict(extra="allow")

    gap_id: str
    provider_id: Optional[str] = None
    provider_display_name: Optional[str] = None
    start_date: str
    end_date: str
    gap_days: int
    severity: str
    rule_name: Optional[str] = None
    rationale: Optional[str] = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    suggested_records_to_request: dict[str, Any] = Field(default_factory=dict)


class MissingRecordsSummary(BaseModel):
    total_gaps: int = 0
    provider_gap_count: int = 0
    global_gap_count: int = 0
    high_severity_count: int = 0
    medium_severity_count: int = 0
    patient_scope_count: int = 0
    unassigned_events_excluded: int = 0


class MissingRecordsExtension(BaseModel):
    model_config = ConfigDict(extra="allow")

    version: str = "1.0"
    generated_at: datetime | str
    ruleset: dict[str, Any] = Field(default_factory=dict)
    gaps: list[MissingRecordsGap] = Field(default_factory=list)
    summary: MissingRecordsSummary = Field(default_factory=MissingRecordsSummary)


class MissingRecordRequestDateRange(BaseModel):
    from_date: str
    to_date: str


class MissingRecordRequestGapReference(BaseModel):
    gap_id: Optional[str] = None
    gap_days: Optional[int] = None
    severity: str


class MissingRecordRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    request_id: str
    provider_id: str
    provider_display_name: str
    request_date_range: MissingRecordRequestDateRange
    gap_reference: MissingRecordRequestGapReference
    request_priority: str
    request_type: str
    request_rationale: str


class MissingRecordRequestsExtension(BaseModel):
    model_config = ConfigDict(extra="allow")

    version: str = "1.0"
    generated_at: datetime | str
    requests: list[MissingRecordRequest] = Field(default_factory=list)


class BillingLine(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    provider_entity_id: Optional[str] = None
    service_date: Optional[str] = None
    post_date: Optional[str] = None
    description: str = ""
    code: Optional[str] = None
    units: Optional[str] = None
    amount: str = "0.00"
    amount_type: str = "unknown"
    source_page_numbers: list[int] = Field(default_factory=list)
    source_document_id: Optional[str] = None
    citation_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    flags: list[str] = Field(default_factory=list)


class BillingLinesExtension(BaseModel):
    model_config = ConfigDict(extra="allow")

    line_count: int = 0
    billing_pages_count: int = 0
    lines: list[BillingLine] = Field(default_factory=list)


class SpecialsSummaryExtension(BaseModel):
    model_config = ConfigDict(extra="allow")

    totals: dict[str, Any] = Field(default_factory=dict)
    by_provider: list[dict[str, Any]] = Field(default_factory=list)
    coverage: dict[str, Any] = Field(default_factory=dict)
    dedupe: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.0
    flags: list[str] = Field(default_factory=list)


class LitigationExtensions(BaseModel):
    model_config = ConfigDict(extra="allow")

    claim_rows: list[dict[str, Any]] = Field(default_factory=list)
    causation_chains: list[dict[str, Any]] = Field(default_factory=list)
    case_collapse_candidates: list[dict[str, Any]] = Field(default_factory=list)
    defense_attack_paths: list[dict[str, Any]] = Field(default_factory=list)
    objection_profiles: list[dict[str, Any]] = Field(default_factory=list)
    evidence_upgrade_recommendations: list[dict[str, Any]] = Field(default_factory=list)
    quote_lock_rows: list[dict[str, Any]] = Field(default_factory=list)
    contradiction_matrix: list[dict[str, Any]] = Field(default_factory=list)
    narrative_duality: dict[str, Any] = Field(default_factory=dict)
    comparative_pattern_engine: dict[str, Any] = Field(default_factory=dict)
    citation_fidelity: dict[str, Any] = Field(default_factory=dict)
