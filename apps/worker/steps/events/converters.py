from typing import List, Dict
from datetime import date
from packages.shared.models import Event, Citation
from .synthesis_domain import ClinicalAtom, ClinicalCitation
from .clinical_filtering import normalize_text

def build_citation_map(citations: List[Citation]) -> Dict[str, Citation]:
    return {c.citation_id: c for c in citations}

def event_to_atoms(event: Event, citation_map: Dict[str, Citation]) -> List[ClinicalAtom]:
    atoms = []
    
    # Handle Date: If range, use start. If None, skip? Or use None?
    # Clustering logic groups by date. None date atoms will be skipped there or need handling.
    event_date = None
    if event.date and event.date.value:
        if isinstance(event.date.value, date):
            event_date = event.date.value
        else:
             # DateRange
             event_date = event.date.value.start

    for fact in event.facts:
        clinical_citations = []
        cids = fact.citation_ids or []
        if fact.citation_id and fact.citation_id not in cids:
            cids.append(fact.citation_id)
            
        for cid in cids:
            cit = citation_map.get(cid)
            if cit:
                clinical_citations.append(ClinicalCitation(
                    doc_id=cit.source_document_id,
                    page=cit.page_number,
                    span=None 
                ))
        
        atoms.append(ClinicalAtom(
            date=event_date,
            text=normalize_text(fact.text),
            kind="fact", # could use fact.kind
            citations=clinical_citations,
            provider=event.provider_id,
            facility=None,
            anatomy=None,
            confidence=event.confidence
        ))
        
    return atoms
