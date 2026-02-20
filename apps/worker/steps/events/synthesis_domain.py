from dataclasses import dataclass, field
from typing import List, Optional, Set
from datetime import date as date_type

@dataclass
class ClinicalCitation:
    doc_id: str
    page: int
    span: Optional[str] = None

@dataclass
class ClinicalAtom:
    date: date_type
    text: str  # normalized
    kind: str  # procedure/diagnosis/imaging/med/encounter/plan/finding/etc.
    citations: List[ClinicalCitation]
    provider: Optional[str] = None
    facility: Optional[str] = None
    anatomy: Optional[str] = None
    confidence: Optional[int] = None

@dataclass
class ClinicalEvent:
    date: date_type
    event_type: str 
    title: str
    atoms: List[ClinicalAtom]
    citations: List[ClinicalCitation]
    
    # Synthesized Fields (Step 1)
    procedures: Set[str] = field(default_factory=set)
    fractures: Set[str] = field(default_factory=set)
    tears: Set[str] = field(default_factory=set)
    infections: Set[str] = field(default_factory=set)
    fragments: Set[str] = field(default_factory=set)
    plans: Set[str] = field(default_factory=set)
    
    # CASEMARK ADAPTATION: Structured Encounter Fields
    reason_for_visit: Optional[str] = None
    chief_complaint: Optional[str] = None
    exam_findings: List[str] = field(default_factory=list)
    treatment_plan: List[str] = field(default_factory=list)
    diagnoses: List[str] = field(default_factory=list)
    coding: dict = field(default_factory=dict)
    
    provider: Optional[str] = None
    facility: Optional[str] = None
