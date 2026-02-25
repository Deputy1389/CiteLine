"""
Step 19 — LLM Reasoning (Modern Google-GenAI)
"""
from __future__ import annotations
import json
import logging
import os
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from google import genai
from google.genai import types

from packages.shared.models import EvidenceGraph, Event, Provider, RunConfig, Warning
from apps.worker.lib.llm_skills_adapter import to_skill_event

ROOT = Path(__file__).resolve().parents[3]
load_dotenv(dotenv_path=ROOT / ".env")

logger = logging.getLogger(__name__)

def _route_high_value_events(events: list[Event], providers: list[Provider], config: RunConfig) -> list[dict]:
    eligible = [e for e in events if e.confidence >= config.llm_reasoning_min_confidence and len(e.citation_ids) >= config.llm_reasoning_min_citations]
    return [to_skill_event(e, providers) for e in eligible[:config.llm_reasoning_max_events]]

def _prompt_analyst_skill(event_rows: list[dict]) -> str:
    return f"""Analyze these medical events. Output ONLY valid JSON.
INPUT: {json.dumps(event_rows)}
SCHEMA:
{{
  "materiality": [ {{ "event_id": "string", "rank": integer, "tier": "A"|"B", "rationale": "string" }} ],
  "contradictions": [ {{ "left_event_id": "string", "right_event_id": "string", "issue": "string" }} ],
  "risk_flags": [ {{ "event_id": "string", "issue": "string" }} ]
}}"""

def run_llm_reasoning(evidence_graph: EvidenceGraph, providers: list[Provider], config: RunConfig) -> tuple[dict, list[Warning]]:
    extensions, warnings = {}, []
    if os.getenv("MOCK_LLM") == "true":
        logger.info("MOCK_LLM is true, returning mock reasoning.")
        extensions["llm_analysis"] = {
            "materiality": [{"event_id": e.event_id, "rank": 1, "tier": "A", "rationale": "Mock"} for e in evidence_graph.events[:3]],
            "contradictions": [],
            "risk_flags": []
        }
        return extensions, warnings

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key: return extensions, warnings

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=config.gemini_model,
            contents=_prompt_analyst_skill(_route_high_value_events(evidence_graph.events, providers, config)),
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        
        raw_text = response.text
        # Clean markdown if present
        if "```json" in raw_text:
            raw_text = raw_text.split("```json")[1].split("```")[0].strip()
        
        data = json.loads(raw_text)
        extensions["llm_analysis"] = data
        return extensions, warnings
    except Exception as exc:
        logger.error(f"LLM Step 19 failed: {exc}")
        return extensions, warnings
