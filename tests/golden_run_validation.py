"""
End-to-End "Golden Run" Validation.
"""
import sys
import os
import logging
import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone

# Add root to sys.path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from apps.worker.pipeline import run_pipeline
from packages.db.database import get_session, init_db
from packages.db.models import Run, Matter, Firm, SourceDocument
from packages.shared.models import EvidenceGraph, NarrativeChronology

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("GoldenRun")

def setup_test_matter():
    """Create a high-density test matter."""
    with get_session() as session:
        firm = Firm(id="firm_golden", name="Golden Validation Firm")
        session.merge(firm)
        
        matter = Matter(id="matter_golden", firm_id="firm_golden", title="Golden High-Density Case")
        session.merge(matter)
        
        test_docs = [
            ("doc_ed", "doc_ed.pdf"),
            ("doc_ortho", "doc_ortho.pdf"),
            ("doc_esi", "doc_esi.pdf")
        ]
        
        for doc_id, filename in test_docs:
            path = Path("data/uploads") / filename
            if not path.exists():
                logger.error(f"{filename} missing from data/uploads!")
                continue
            
            file_bytes = path.read_bytes()
            sha256 = hashlib.sha256(file_bytes).hexdigest()
            
            doc = SourceDocument(
                id=doc_id,
                matter_id="matter_golden",
                filename=filename,
                mime_type="application/pdf",
                sha256=sha256,
                bytes=len(file_bytes)
            )
            session.merge(doc)
        
        run_id = "run_golden_v2"
        run = Run(
            id=run_id,
            matter_id="matter_golden",
            status="pending",
            config_json={
                "enable_llm_reasoning": True,
                "gemini_model": "gemini-1.5-flash"
            },
        )
        session.merge(run)
        session.commit()
        return run_id

def validate_results(run_id: str):
    """Deep audit of the pipeline results."""
    # 1. Check Evidence Graph
    eg_path = Path("data/artifacts") / run_id / "evidence_graph.json"
    if not eg_path.exists():
        logger.error(f"evidence_graph.json missing at {eg_path}")
        return False
        
    with open(eg_path, "r") as f:
        data = json.load(f)
        
    graph_data = data["outputs"]["evidence_graph"]
    graph = EvidenceGraph.model_validate(graph_data)
    logger.info(f"Evidence Graph: {len(graph.events)} events, {len(graph.citations)} citations.")
    
    if not graph.narrative_chronology:
        logger.error("Narrative Chronology missing!")
        return False
        
    narrative = graph.narrative_chronology
    logger.info(f"Narrative Chronology: {len(narrative.entries)} entries.")
    
    for entry in narrative.entries:
        if not entry.event_ids or not entry.citation_ids:
            logger.error(f"Row {entry.row_id} anchoring failed.")
            return False
            
    return True

if __name__ == "__main__":
    os.environ["MOCK_LLM"] = "true"
    init_db()
    run_id = setup_test_matter()
    if run_id:
        logger.info(f"Starting Golden Run: {run_id}")
        run_pipeline(run_id)
        if validate_results(run_id):
            logger.info("GOLDEN RUN SUCCESSFUL.")
        else:
            sys.exit(1)
