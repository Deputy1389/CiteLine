"""
Step 19 — LLM Reasoning (Skill-Based Routing)

Implements a two-stage reasoning pipeline:
1. Analyst Skill: Strategic Materiality & Contradiction Proposal.
2. Integrity Auditor: Deterministic validation of LLM claims.

Architecture:
- Deterministic Routing: Only High-Stakes events are sent to the LLM.
- Strict JSON: 100% schema enforcement.
- Fail-Safe: Hallucinated references cause immediate rejection of the claim.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Optional
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# Search for .env in root directory
ROOT = Path(__file__).resolve().parents[3]
env_path = ROOT / ".env"
load_dotenv(dotenv_path=env_path)

import google.generativeai as genai
from packages.shared.models import EvidenceGraph, Event, Provider, RunConfig, Warning
from apps.worker.lib.llm_skills_adapter import to_skill_event

logger = logging.getLogger(__name__)

# Only High-Stakes types go to the Strategic Analyst
HIGH_STAKES_TYPES = {
    "IMAGING_STUDY",
    "ER_VISIT",
    "PROCEDURE",
    "ORTHOPEDIC_CONSULT"
}

def _route_high_value_events(events: list[Event], providers: list[Provider]) -> list[dict]:
    """
    Deterministic Router: Filter for exportable, cited, high-stakes events.
    Includes first/last clinical notes for context.
    """
    eligible = [
        e for e in events 
        if e.confidence >= 30 
        and len(e.citation_ids) >= 1 
        and not any(f.technical_noise for f in e.facts)
    ]
    
    high_stakes = [e for e in eligible if e.event_type.value in HIGH_STAKES_TYPES]
    
    # Add context (first and last events if not already included)
    context_ids = {e.event_id for e in high_stakes}
    if eligible:
        if eligible[0].event_id not in context_ids:
            high_stakes.insert(0, eligible[0])
        if eligible[-1].event_id not in context_ids:
            high_stakes.append(eligible[-1])
            
    # Cap at 50 high-value events to maximize reasoning quality and stay in free tier
    return [to_skill_event(e, providers) for e in high_stakes[:50]]


def _prompt_analyst_skill(event_rows: list[dict]) -> str:
    events_json = json.dumps(event_rows)
    return f"""You are a senior litigation analyst. Analyze these HIGH-STAKES medical events.
Output ONLY valid JSON.

SKILL: Strategic Materiality + Contradiction Detector
INPUT: {events_json}

OUTPUT SCHEMA:
{{
  "materiality": [
    {{ "event_id": "string", "rank": integer, "tier": "A"|"B", "rationale": "string" }}
  ],
  "contradictions": [
    {{ "left_event_id": "string", "right_event_id": "string", "issue": "string", "severity": "HIGH"|"MEDIUM" }}
  ],
  "risk_flags": [
    {{ "event_id": "string", "issue": "string", "why_it_matters": "string" }}
  ]
}}

RULES:
1. Use ONLY event_ids from the input.
2. 'materiality' rank 1-10. Tier A = Trial Winning, Tier B = Significant.
3. 'contradictions' must be clinical (e.g. imaging says no fracture, but ortho note says fracture)."""


def _audit_and_clean(data: dict, valid_ids: set[str]) -> tuple[dict, list[str]]:
    """
    Integrity Auditor: Deterministic verification of LLM output.
    Returns (cleaned_data, list_of_dropped_issues).
    """
    issues = []
    cleaned = {
        "materiality": [],
        "contradictions": [],
        "risk_flags": []
    }
    
    # Audit Materiality
    for item in data.get("materiality", []):
        eid = item.get("event_id")
        if eid in valid_ids:
            cleaned["materiality"].append(item)
        else:
            issues.append(f"hallucinated_materiality_id: {eid}")
            
    # Audit Contradictions
    for item in data.get("contradictions", []):
        l_id = item.get("left_event_id")
        r_id = item.get("right_event_id")
        if l_id in valid_ids and r_id in valid_ids:
            cleaned["contradictions"].append(item)
        else:
            issues.append(f"hallucinated_contradiction_pair: {l_id}/{r_id}")
            
    # Audit Risk Flags
    for item in data.get("risk_flags", []):
        eid = item.get("event_id")
        if eid in valid_ids:
            cleaned["risk_flags"].append(item)
        else:
            issues.append(f"hallucinated_risk_id: {eid}")
            
    return cleaned, issues


def run_llm_reasoning(
    evidence_graph: EvidenceGraph,
    providers: list[Provider],
    config: RunConfig,
) -> tuple[dict, list[Warning]]:
    """
    Run the lean Analyst + Auditor pipeline.
    """
    warnings: list[Warning] = []
    extensions: dict = {}

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return extensions, warnings

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            model_name=config.gemini_model, # gemini-1.5-flash
            generation_config={"response_mime_type": "application/json", "temperature": 0.1}
        )

        # 1. Routing
        high_value_payload = _route_high_value_events(evidence_graph.events, providers)
        if not high_value_payload:
            return extensions, warnings

        # 2. Analyst Skill
        t0 = time.time()
        response = model.generate_content(_prompt_analyst_skill(high_value_payload))
        raw_data = json.loads(response.text)
        
        # 3. Integrity Auditor
        valid_ids = {e.event_id for e in evidence_graph.events}
        clean_data, audit_issues = _audit_and_clean(raw_data, valid_ids)
        
        if audit_issues:
            logger.warning(f"LLM Integrity Audit dropped {len(audit_issues)} hallucinated claims.")

        # 4. Packaging & Annotation
        extensions["llm_analysis"] = clean_data
        _annotate_graph(evidence_graph.events, clean_data)
        
        extensions["llm_metadata"] = {
            "model": config.gemini_model,
            "events_routed": len(high_value_payload),
            "audit_issues_dropped": len(audit_issues),
            "material_count": len(clean_data["materiality"]),
            "contradiction_count": len(clean_data["contradictions"]),
            "risk_count": len(clean_data["risk_flags"]),
            "run_timestamp": datetime.utcnow().isoformat()
        }

    except Exception as exc:
        logger.warning(f"LLM Step 19: reasoning failed: {exc}")
        warnings.append(Warning(code="LLM_ERROR", message=f"LLM reasoning failed: {str(exc)[:100]}"))

    return extensions, warnings


def _annotate_graph(events: list[Event], data: dict):
    """Back-port LLM insights into the event extensions for UI display."""
    materiality_map = {m["event_id"]: m for m in data.get("materiality", [])}
    risk_map = {r["event_id"]: r for r in data.get("risk_flags", [])}

    for evt in events:
        if evt.event_id in materiality_map:
            m = materiality_map[evt.event_id]
            evt.extensions["llm_materiality_rank"] = m.get("rank")
            evt.extensions["llm_materiality_tier"] = m.get("tier")
            evt.extensions["llm_materiality_rationale"] = m.get("rationale")
            
        if evt.event_id in risk_map:
            r = risk_map[evt.event_id]
            evt.extensions["llm_deposition_risk"] = r.get("issue")
