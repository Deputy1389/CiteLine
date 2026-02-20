"""
Step 12a — Narrative Synthesis (Refactored).
Deterministic pipeline for clinical event synthesis.
"""
import logging
from typing import List, Optional
from packages.shared.models import Event, Citation, Provider, CaseInfo

from .events.synthesis_domain import ClinicalAtom, ClinicalEvent
from .events.converters import event_to_atoms, build_citation_map
from .events.clinical_clustering import cluster_atoms_into_events
from .events.clinical_extraction import extract_fields
from .events.clinical_rendering import render_report
from .events.anatomy_filter import infer_dominant_domain, filter_anatomy_anomalies

logger = logging.getLogger(__name__)

def synthesize_narrative(
    events: List[Event], 
    providers: List[Provider], 
    all_citations: List[Citation],
    case_info: CaseInfo
) -> str:
    """
    Synthesizes the event list into a professional narrative using deterministic logic.
    """
    logger.info(f"Synthesizing narrative for {len(events)} events with {len(all_citations)} citations")
    
    # 1. Build Citation Map
    citation_map = build_citation_map(all_citations)
    
    # 2. Convert to Atoms
    all_atoms: List[ClinicalAtom] = []
    for event in events:
        atoms = event_to_atoms(event, citation_map)
        all_atoms.extend(atoms)
        
    # 3. Anatomy Domain Filtering (Sanity Pass)
    domain = infer_dominant_domain(all_atoms)
    logger.info(f"Inferred dominant anatomy domain: {domain}")
    filtered_atoms = filter_anatomy_anomalies(all_atoms, domain)
    
    # 4. Cluster Atoms into Clinical Events (Deterministic)
    clinical_events = cluster_atoms_into_events(filtered_atoms)
    
    # 5. Extract Fields (Procedures, Diagnoses, etc.)
    for ce in clinical_events:
        extract_fields(ce)
        
    # 6. Render Report
    report = render_report(clinical_events, case_info)
    
    return report
