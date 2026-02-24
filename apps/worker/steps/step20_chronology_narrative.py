"""
Step 20 — Anchored Chronology Narrative

Uses LLM reasoning to synthesize high-value Evidence Graph events into a
readable narrative chronology while maintaining strict claim-level anchoring.
"""
from __future__ import annotations
import logging
from packages.shared.models import EvidenceGraph, Provider, RunConfig, Warning
from apps.worker.lib.chronology_narrator import generate_anchored_narrative

logger = logging.getLogger(__name__)

def run_chronology_narrative(
    evidence_graph: EvidenceGraph,
    providers: list[Provider],
    config: RunConfig,
) -> list[Warning]:
    """
    Step 20: Generate the anchored narrative and attach it to the graph.
    """
    warnings: list[Warning] = []
    
    if not config.enable_llm_reasoning:
        logger.info("LLM reasoning disabled, skipping Step 20.")
        return warnings

    try:
        logger.info("Step 20: Generating anchored narrative...")
        narrative = generate_anchored_narrative(evidence_graph, providers, config)
        evidence_graph.narrative_chronology = narrative
        logger.info(f"Step 20: Generated {len(narrative.entries)} narrative entries.")
        
    except Exception as exc:
        logger.error(f"Step 20: Narrative generation failed: {exc}")
        warnings.append(Warning(code="NARRATIVE_ERROR", message=f"Anchored narrative generation failed: {str(exc)[:100]}"))

    return warnings
