from packages.shared.models import (
    EvidenceGraph,
    Event,
    EventType,
    DateStatus,
    DateSource,
    PageType,
    RunConfig,
    Warning as PipelineWarning,
)
import logging

logger = logging.getLogger(__name__)

def run_litigation_integrity_pass(
    evidence_graph: EvidenceGraph,
    config: RunConfig,
) -> list[PipelineWarning]:
    """
    Final integrity check (Clause V).
    Enforces strict date validation and DOI propagation bans.
    """
    warnings = []
    page_map = {p.page_number: p for p in evidence_graph.pages}
    
    _BAN_TYPES = (PageType.PT_NOTE, PageType.BILLING, PageType.DISCHARGE_SUMMARY)
    high_stakes = (EventType.HOSPITAL_ADMISSION, EventType.PROCEDURE, EventType.IMAGING_STUDY)

    vetted_events = []
    for event in evidence_graph.events:
        drop_event = False
        
        # 1. Check Date Status
        if event.date:
            # Enforce DOI ban for summary pages (Double Check)
            is_summary_page = any(
                page_map.get(pg).page_type in _BAN_TYPES 
                for pg in event.source_page_numbers 
                if pg in page_map
            )
            
            if is_summary_page and event.date.source == DateSource.PROPAGATED:
                # This is a DOI propagation violation
                event.date.value = None
                event.date.status = DateStatus.UNDATED
                event.flags.append("DOI_PROPAGATION_BAN_VIOLATION")
                warnings.append(PipelineWarning(
                    code="INTEGRITY_VIOLATION",
                    message=f"Event {event.event_id} on summary page stripped of propagated DOI.",
                    page=event.source_page_numbers[0] if event.source_page_numbers else 0
                ))

            # 2. High-Stakes Explicit Date Check (Clause IV/V)
            if event.event_type in high_stakes:
                if event.date.status not in (DateStatus.EXPLICIT, DateStatus.RANGE):
                    if event.date.source == DateSource.PROPAGATED:
                        event.flags.append("UNVERIFIED_HIGH_STAKES_DATE")
                        # For litigation grade, we might want to downgrade confidence
                        event.confidence = min(event.confidence, config.high_stakes_confidence_cap)
        
        vetted_events.append(event)
    
    evidence_graph.events = vetted_events
    return warnings
