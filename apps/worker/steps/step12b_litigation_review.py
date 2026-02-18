
import logging
from packages.shared.models import Event, Warning
from packages.shared.storage import save_artifact
from apps.worker.lib.litigation_review import LitigationReviewer

logger = logging.getLogger(__name__)

def run_litigation_review(
    run_id: str,
    events: list[Event],
    page_text_by_number: dict[int, str]
) -> tuple[dict, list[Warning]]:
    """
    Execute Litigation Grade Review on the extracted events.
    Returns:
        (checklist_dict, warnings_list)
    """
    logger.info(f"[{run_id}] Running Litigation Grade Review")
    
    warnings = []
    
    # 1. Prepare Text content (concatenate all pages)
    # Sort by page number to be safe
    full_text = "\n".join([page_text_by_number[k] for k in sorted(page_text_by_number.keys())])
    
    # 2. Initialize Reviewer
    reviewer = LitigationReviewer(run_id)
    reviewer.load_from_memory(events=events, text_content=full_text)
    
    # 3. Run Checks
    checklist = reviewer.run_checks()
    
    # 4. Generate Report
    report_md = reviewer.generate_report()
    
    # 5. Save Artifacts
    if checklist:
        # Save JSON
        import json
        json_bytes = json.dumps(checklist, indent=2).encode('utf-8')
        save_artifact(run_id, "qa_litigation_checklist.json", json_bytes)
        
        # Save MD
        md_bytes = report_md.encode('utf-8')
        save_artifact(run_id, "litigation_review.md", md_bytes)
        
    # 6. Warn on failure
    if not checklist['pass']:
        msg = f"Litigation Review FAILED (Score: {checklist['score_0_100']}). See litigation_review.md"
        logger.warning(f"[{run_id}] {msg}")
        warnings.append(Warning(
            code="LITIGATION_REVIEW_FAIL",
            message=msg
        ))
        
    return checklist, warnings
