"""
Step 19 — LLM Reasoning (Gemini Flash)

Optional semantic layer: Strategic Materiality Ranker, Contradiction Detector,
Causation Chain Builder, and Deposition Risk Scanner.

Uses the CiteLine Gemini Skills JSON Contracts (v1) where possible,
while maintaining backward compatibility for the "Strategic Moat" UI.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any
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

_MAX_EVENTS_FOR_LLM = 250  # cap payload size


def _build_event_payload(events: list[Event], providers: list[Provider]) -> list[dict]:
    """Build structured event summaries for LLM consumption using the Skills adapter."""
    return [to_skill_event(e, providers) for e in events[:_MAX_EVENTS_FOR_LLM]]


def _prompt_unified_strategic_analysis(event_rows: list[dict], mechanism: str, doi: str) -> str:
    events_json = json.dumps(event_rows)
    incident_ids = [e["event_id"] for e in event_rows if e["event_type"] in ("ER_VISIT", "CLINICAL_NOTE")][:3]
    
    return f"""You are a lead trial attorney and medical-legal expert.
Analyze the provided medical events and output ONLY valid JSON.

SKILL SET: CiteLine Unified Strategic Analysis (v1.1)

INPUT:
{{
  "events": {events_json},
  "incident": {{
    "doi_date_iso": "{doi}",
    "mechanism_text": "{mechanism}",
    "incident_event_ids": {json.dumps(incident_ids)}
  }}
}}

OUTPUT SCHEMA (STRICT):
{{
  "causation": {{
    "chain": [
      {{ "order": integer, "node_type": "INCIDENT"|"SYMPTOM"|"DIAGNOSIS"|"IMAGING"|"TREATMENT", "event_id": "string", "claim": "string" }}
    ],
    "gaps": [ {{ "gap_type": "MISSING_RECORD"|"TEMPORAL_GAP", "description": "string" }} ],
    "case_summary": "string (2-3 sentences)",
    "risk_score": integer (0-100)
  }},
  "strategy": {{
    "contradictions": [
      {{ "left_event_id": "string", "right_event_id": "string", "kind": "DIRECT"|"LIKELY", "explanation": "string" }}
    ],
    "risk_flags": [
      {{ "risk_id": "string", "severity": "HIGH"|"CRITICAL", "issue": "string", "why_it_matters": "string", "recommended_fix": "string" }}
    ],
    "strategic_recommendations": ["string"]
  }},
  "materiality": {{
    "selected": [
      {{ "rank": integer, "event_id": "string", "tier": "A"|"B", "rationale": "string" }}
    ]
  }}
}}

RULES:
1. Every event_id MUST exist in the input.
2. Focus on high-stakes clinical findings.
3. 'strategic_recommendations' should be actionable advice for the attorney.
4. Output valid JSON only."""


def _validate_event_ids(data: Any, valid_ids: set[str]) -> Any:
    """Recursively remove references to non-existent event_ids from LLM output."""
    if isinstance(data, dict):
        cleaned = {}
        for k, v in data.items():
            if k in ("event_id", "left_event_id", "right_event_id", "incident_event_ids", "neighbor_event_ids") and isinstance(v, str):
                if v and v != "null" and v not in valid_ids:
                    cleaned[k] = None
                    continue
            cleaned[k] = _validate_event_ids(v, valid_ids)
        return cleaned
    elif isinstance(data, list):
        return [_validate_event_ids(item, valid_ids) for item in data]
    return data


def run_llm_reasoning(
    evidence_graph: EvidenceGraph,
    providers: list[Provider],
    config: RunConfig,
) -> tuple[dict, list[Warning]]:
    """
    Run Gemini Flash LLM reasoning using CiteLine Skills layer.
    """
    warnings: list[Warning] = []
    extensions: dict = {}

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.info("LLM Step 19: GEMINI_API_KEY not set — skipping reasoning")
        return extensions, warnings

    try:
        model_name = config.gemini_model
        if not model_name.startswith("models/"):
            model_name = f"models/{model_name}"
            
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            model_name=model_name,
            generation_config={
                "response_mime_type": "application/json",
                "temperature": 0.1,
            }
        )

        events = evidence_graph.events
        valid_ids = {e.event_id for e in events}
        event_rows = _build_event_payload(events, providers)

        if not event_rows:
            return extensions, warnings

        # Infer DOI and Mechanism
        doi = "unknown"
        mechanism = "accident"
        for row in event_rows:
            if row["event_type"] == "ER_VISIT" and row["date_iso"]:
                doi = row["date_iso"]
                break
        if doi == "unknown" and event_rows and event_rows[0].get("date_iso"):
            doi = event_rows[0]["date_iso"]

        # ── Unified Strategic Analysis ──────────────────────────────────
        t0 = time.time()
        response = model.generate_content(_prompt_unified_strategic_analysis(event_rows, mechanism, doi))
        data = json.loads(response.text)
        data = _validate_event_ids(data, valid_ids)
        
        # ── Backward Compatibility for UI ───────────────────────────────
        causation = data.get("causation", {})
        strategy = data.get("strategy", {})
        
        extensions["llm_causation"] = {
            "causation_assessments": [
                {"event_id": node["event_id"], "causal_nexus_score": 90, "causal_chain": node["claim"]}
                for node in causation.get("chain", []) if node.get("event_id")
            ],
            "case_summary": causation.get("case_summary", ""),
            "risk_score": causation.get("risk_score", 50)
        }
        
        extensions["llm_strategy"] = {
            "contradiction_flags": [
                {"event_id": c["left_event_id"], "event_id_b": c["right_event_id"], "contradiction_type": c["kind"], "description": c["explanation"]}
                for c in strategy.get("contradictions", []) if c.get("left_event_id")
            ],
            "defense_vulnerabilities": [
                {"event_id": r["event_id"] if "event_id" in r else (r["evidence"][0]["event_id"] if r.get("evidence") else None), 
                 "vulnerability": r["issue"], "risk_level": r["severity"].lower()}
                for r in strategy.get("risk_flags", [])
            ],
            "strategic_recommendations": strategy.get("strategic_recommendations", [])
        }
        
        # ── New Skills Data ─────────────────────────────────────────────
        extensions["skills_v1"] = data
        
        # ── Annotate Events ───────────────────────────────────────────────
        _annotate_events(events, data)

        extensions["llm_metadata"] = {
            "model": config.gemini_model,
            "events_analyzed": len(event_rows),
            "run_timestamp": datetime.utcnow().isoformat(),
            "causation_nodes": len(causation.get("chain", [])),
            "contradiction_count": len(strategy.get("contradictions", [])),
            "risk_flag_count": len(strategy.get("risk_flags", [])),
            "material_event_count": len(data.get("materiality", {}).get("selected", [])),
        }

    except Exception as exc:
        logger.warning(f"LLM Step 19: Unexpected error: {exc}", exc_info=True)
        warnings.append(Warning(
            code="LLM_ERROR",
            message=f"LLM reasoning failed: {str(exc)[:200]}",
        ))

    return extensions, warnings


def _annotate_events(events: list[Event], analysis: dict):
    """Back-port LLM insights into the event models for UI display."""
    causation = analysis.get("causation", {})
    materiality = analysis.get("materiality", {})
    
    causation_map = {node["event_id"]: node for node in causation.get("chain", []) if node.get("event_id")}
    materiality_map = {item["event_id"]: item for item in materiality.get("selected", []) if item.get("event_id")}

    for evt in events:
        if evt.event_id in causation_map:
            node = causation_map[evt.event_id]
            evt.extensions["llm_causation_claim"] = node.get("claim")
            evt.extensions["llm_node_type"] = node.get("node_type")
            
        if evt.event_id in materiality_map:
            item = materiality_map[evt.event_id]
            evt.extensions["llm_materiality_rank"] = item.get("rank")
            evt.extensions["llm_materiality_tier"] = item.get("tier")
            evt.extensions["llm_materiality_rationale"] = item.get("rationale")
