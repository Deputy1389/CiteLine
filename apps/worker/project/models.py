from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ChronologyProjectionEntry(BaseModel):
    event_id: str
    date_display: str
    provider_display: str
    event_type_display: str
    patient_label: str = "Unknown Patient"
    facts: list[str] = Field(default_factory=list)
    verbatim_flags: list[bool] = Field(default_factory=list)
    citation_display: str = ""
    confidence: int = 0


class ChronologyProjection(BaseModel):
    generated_at: datetime
    entries: list[ChronologyProjectionEntry] = Field(default_factory=list)
    select_timeline: bool = True
