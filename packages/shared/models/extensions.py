from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .enums import ClaimType


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


# ── ClaimEdge: typed analytical primitive ──────────────────────────────────


class ClaimEdge(BaseModel):
    """Typed representation of a single claim row.

    Replaces ad-hoc ``dict`` claim rows with validated fields while
    preserving the same serialized JSON shape.  A ``.get()`` bridge
    method is provided so existing ``r.get("field")`` call-sites work
    during migration.
    """

    model_config = ConfigDict(extra="allow")

    id: str
    event_id: str
    patient_label: str = "Unknown Patient"
    claim_type: str
    date: str = "unknown"
    body_region: str = "general"
    provider: str = "Unknown"
    assertion: str = ""
    citations: list[str] = Field(default_factory=list)
    support_score: int = 0
    support_strength: str = "Weak"
    flags: list[str] = Field(default_factory=list)
    materiality_weight: int = 1
    selection_score: int = 0

    @field_validator("claim_type")
    @classmethod
    def _validate_claim_type(cls, value: str) -> str:
        if value not in {c.value for c in ClaimType}:
            raise ValueError(f"Invalid claim_type: {value}")
        return value

    def get(self, key: str, default: Any = None) -> Any:
        """Dict-style access bridge for migration compatibility."""
        try:
            return getattr(self, key)
        except AttributeError:
            return default


# ── Typed sub-models for litigation structures ─────────────────────────────


class CausationRung(BaseModel):
    model_config = ConfigDict(extra="allow")

    rung_order: int
    event_id: str = ""
    rung_type: str = ""
    body_region: str = "general"
    date: str = "unknown"
    citation_ids: list[str] = Field(default_factory=list)
    temporal_gap_from_previous_days: Optional[int] = None
    integrity_score: int = 0
    provider_reliability_multiplier: float = 0.8


class CausationChain(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    body_region: str = "general"
    rungs: list[CausationRung | dict[str, Any]] = Field(default_factory=list)
    chain_integrity_score: int = 0
    break_points: list[int] = Field(default_factory=list)
    missing_rungs: list[str] = Field(default_factory=list)
    incident_date: Optional[str] = None
    temporal_decay_penalty: int = 0
    provider_reliability_multiplier_avg: float = 0.8
    provider_reliability_penalty: int = 0
    max_days_from_incident: int = 0


class CaseCollapseCandidate(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    fragility_type: str
    score_components: dict[str, Any] = Field(default_factory=dict)
    fragility_score: int = 0
    support_rows: list[dict[str, Any]] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)
    why: str = ""
    confidence_tier: str = "Low"
    incident_date: Optional[str] = None


class DefenseAttackPath(BaseModel):
    model_config = ConfigDict(extra="allow")

    attack: str
    path: str = ""
    confidence_tier: str = "Low"
    citations: list[str] = Field(default_factory=list)
    score: int = 0


class ContradictionEntry(BaseModel):
    model_config = ConfigDict(extra="allow")

    category: str
    supporting: dict[str, Any] = Field(default_factory=dict)
    contradicting: dict[str, Any] = Field(default_factory=dict)
    strength_delta: int = 0
    window_days: Optional[int] = None


class QuoteLockRow(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    date: str = "unknown"
    claim_type: str = ""
    quote: str = ""
    citation: str = ""
    event_id: str = ""


class CitationFidelity(BaseModel):
    model_config = ConfigDict(extra="allow")

    claim_rows_total: int = 0
    claim_rows_anchored: int = 0
    claim_row_anchor_ratio: float = 1.0


class NarrativePoint(BaseModel):
    model_config = ConfigDict(extra="allow")

    date: str = "unknown"
    assertion: str = ""
    claim_type: str = ""
    support_strength: str = "Weak"
    citations: list[str] = Field(default_factory=list)


class DefensePoint(BaseModel):
    model_config = ConfigDict(extra="allow")

    attack: str = ""
    path: str = ""
    confidence_tier: str = "Low"
    citations: list[str] = Field(default_factory=list)


class NarrativeSide(BaseModel):
    model_config = ConfigDict(extra="allow")

    summary: str = ""
    points: list[NarrativePoint | DefensePoint | dict[str, Any]] = Field(default_factory=list)


class NarrativeDuality(BaseModel):
    model_config = ConfigDict(extra="allow")

    plaintiff_narrative: NarrativeSide | dict[str, Any] = Field(default_factory=dict)
    defense_narrative: NarrativeSide | dict[str, Any] = Field(default_factory=dict)


# ── LitigationExtensions ──────────────────────────────────────────────────


class LitigationExtensions(BaseModel):
    model_config = ConfigDict(extra="allow")

    claim_rows: list[ClaimEdge | dict[str, Any]] = Field(default_factory=list)
    causation_chains: list[CausationChain | dict[str, Any]] = Field(default_factory=list)
    case_collapse_candidates: list[CaseCollapseCandidate | dict[str, Any]] = Field(default_factory=list)
    defense_attack_paths: list[DefenseAttackPath | dict[str, Any]] = Field(default_factory=list)
    objection_profiles: list[dict[str, Any]] = Field(default_factory=list)
    evidence_upgrade_recommendations: list[dict[str, Any]] = Field(default_factory=list)
    quote_lock_rows: list[QuoteLockRow | dict[str, Any]] = Field(default_factory=list)
    contradiction_matrix: list[ContradictionEntry | dict[str, Any]] = Field(default_factory=list)
    narrative_duality: NarrativeDuality | dict[str, Any] = Field(default_factory=dict)
    comparative_pattern_engine: dict[str, Any] = Field(default_factory=dict)
    citation_fidelity: CitationFidelity | dict[str, Any] = Field(default_factory=dict)
