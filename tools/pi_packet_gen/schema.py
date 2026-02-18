from __future__ import annotations
from datetime import date
from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class Archetype(str, Enum):
    SOFT_TISSUE = "soft_tissue"
    HERNIATION = "herniation"
    SURGICAL = "surgical"
    COMPLEX_PRIOR = "complex_prior"
    MINOR = "minor"

class Gender(str, Enum):
    MALE = "Male"
    FEMALE = "Female"

class PacketConfig(BaseModel):
    archetype: Archetype
    target_pages: int
    noise_level: str
    seed: int

class Person(BaseModel):
    name: str
    gender: Gender
    dob: date
    mrn: str
    address: str

class MedicalEvent(BaseModel):
    date: date
    provider: str
    facility: str
    event_type: str  # "ED Visit", "Ortho Consult", "PT", "MRI", etc.
    summary: str
    facts: List[str] = Field(default_factory=list)

class DocumentType(str, Enum):
    ED_NOTES = "ED Notes"
    RADIOLOGY_REPORT = "Radiology Report"
    PT_RECORDS = "PT Records"
    ORTHO_VISIT = "Ortho Visit"
    BILLING = "Billing"
    BILLING_LEDGER = "Billing Ledger"
    PRIOR_RECORDS = "Prior Records"
    PROCEDURE_NOTE = "Procedure Note"
    DISCHARGE_SUMMARY = "Discharge Summary"
    WORK_STATUS = "Work Status"
    DISABILITY = "Disability"
    PACKET_NOISE = "Packet Noise"
    MISC = "Misc"

class GeneratedDocument(BaseModel):
    doc_type: DocumentType
    date: date
    provider: str
    page_count: int
    content: Any  # Arbitrary content dict for the renderer
    filename: str

class Case(BaseModel):
    case_id: str
    seed: int
    config: PacketConfig
    patient: Person
    incident_date: date
    incident_description: str
    documents: List[GeneratedDocument] = Field(default_factory=list)
    ground_truth: Dict[str, Any] = Field(default_factory=dict)
