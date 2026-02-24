"""
Step 19 — LLM Reasoning (Gemini Flash)

Optional semantic layer: causation assessment, contradiction detection,
and case summarization via Gemini Flash.

Only runs if config.enable_llm_reasoning is True and GEMINI_API_KEY is set.
All LLM assertions are validated — only references to existing event_ids are kept.
"""
import json
import logging
import os
import time
from typing import Any
from dotenv import load_dotenv

load_dotenv()

import requests

from packages.shared.models import EvidenceGraph, Event, Provider, RunConfig, Warning

logger = logging.getLogger(__name__)

_GEMINI_TIMEOUT = 60  # seconds per request
_MAX_EVENTS_FOR_LLM = 200  # cap payload size
_MAX_FACTS_PER_EVENT = 3   # only top facts per event


def _gemini_call(api_key: str, model: str, prompt: str) -> dict:
    """Make Gemini API call via REST."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.2,
            "maxOutputTokens": 8192,
        }
    }
    resp = requests.post(url, json=payload, timeout=_GEMINI_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(text)


def _build_event_payload(events: list[Event], providers: list[Provider]) -> list[dict]:
    """Build compact event summaries for LLM consumption."""
    provider_map = {p.provider_id: p.normalized_name for p in providers}
    rows = []
    for evt in events[:_MAX_EVENTS_FOR_LLM]:
        date_str = "unknown"
        if evt.date and evt.date.value:
            if hasattr(evt.date.value, 'isoformat'):
                date_str = evt.date.value.isoformat()
            elif hasattr(evt.date.value, 'start'):
                date_str = f"{evt.date.value.start.isoformat()} to {evt.date.value.end.isoformat()}" if evt.date.value.end else evt.date.value.start.isoformat()
        provider_name = provider_map.get(evt.provider_id or "", evt.provider_id or "unknown")
        facts_text = "; ".join(f.text for f in evt.facts[:_MAX_FACTS_PER_EVENT] if f.text)
        rows.append({
            "event_id": evt.event_id,
            "type": evt.event_type.value if hasattr(evt.event_type, "value") else str(evt.event_type),
            "date": date_str,
            "provider": provider_name,
            "facts": facts_text,
        })
    return rows


def _prompt_causation(event_rows: list[dict]) -> str:
    events_json = json.dumps(event_rows)
    return f"""You are a medical-legal analyst. Output ONLY valid JSON, no other text.

Analyze medical events and assess causal relationships to the accident.

Events:
{events_json}

Output JSON format:
{{
  "causation_assessments": [
    {{"event_id": "<event_id from input>", "causal_nexus_score": <0-100>, "causal_chain": "<max 100 chars>"}}
  ],
  "case_summary": "<2-3 sentences>",
  "risk_score": <0-100>
}}

Rules:
- Use ONLY event_ids from the input above
- causal_nexus_score: 90-100=direct causation, 70-89=strongly related, 50-69=probably related, 30-49=possibly related, 0-29=unrelated
- Output valid JSON only - no markdown, no explanation"""


def _prompt_contradictions(event_rows: list[dict]) -> str:
    events_json = json.dumps(event_rows)
    return f"""You are a medical-legal analyst. Output ONLY valid JSON, no other text.

Identify contradictions and defense vulnerabilities in this medical case.

Events:
{events_json}

Output JSON format:
{{
  "contradiction_flags": [
    {{"event_id": "<event_id>", "event_id_b": null, "contradiction_type": "<type>", "description": "<max 100 chars>"}}
  ],
  "defense_vulnerabilities": [
    {{"event_id": "<event_id>", "vulnerability": "<max 100 chars>", "risk_level": "<low/medium/high>"}}
  ]
}}

Rules:
- Use ONLY event_ids from input above
- Output valid JSON only - no markdown, no explanation"""


def _validate_event_ids(data: Any, valid_ids: set[str]) -> Any:
    """Recursively remove references to non-existent event_ids from LLM output."""
    if isinstance(data, dict):
        cleaned = {}
        for k, v in data.items():
            if k in ("event_id", "event_id_a", "event_id_b") and isinstance(v, str):
                if v and v != "null" and v not in valid_ids:
                    cleaned[k] = None  # Nullify invalid reference
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
    Run Gemini Flash LLM reasoning on the evidence graph.

    Returns (extensions_dict, warnings).
    On any failure, returns ({}, [warning]) — never raises.
    """
    warnings: list[Warning] = []
    extensions: dict = {}

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        warnings.append(Warning(
            code="LLM_SKIPPED",
            message="GEMINI_API_KEY not set — LLM reasoning skipped",
        ))
        return extensions, warnings

    try:
        model_name = config.gemini_model
        if model_name in ("gemini-1.5-flash", "gemini-2.0-flash"):
            model_name = "gemini-2.5-flash"

        events = evidence_graph.events
        valid_ids = {e.event_id for e in events}
        event_rows = _build_event_payload(events, providers)

        if not event_rows:
            logger.info("LLM Step 19: No events to analyze — skipping")
            return extensions, warnings

        logger.info(f"LLM Step 19: Starting — {len(event_rows)} events, model={model_name}")

        # ── Prompt 1: Causation assessment ────────────────────────────────
        t0 = time.time()
        causation_data = _gemini_call(api_key, model_name, _prompt_causation(event_rows))
        causation_data = _validate_event_ids(causation_data, valid_ids)
        extensions["llm_causation"] = causation_data
        logger.info(
            f"LLM Step 19: Causation done in {time.time()-t0:.1f}s — "
            f"{len(causation_data.get('causation_assessments', []))} assessments"
        )

        # ── Prompt 2: Contradictions ───────────────────────────────────────
        t0 = time.time()
        contradiction_data = _gemini_call(api_key, model_name, _prompt_contradictions(event_rows))
        contradiction_data = _validate_event_ids(contradiction_data, valid_ids)
        extensions["llm_contradictions"] = contradiction_data
        logger.info(
            f"LLM Step 19: Contradictions done in {time.time()-t0:.1f}s — "
            f"{len(contradiction_data.get('contradiction_flags', []))} flags"
        )

        # ── Annotate individual events with causation scores ───────────────
        causation_by_id: dict[str, dict] = {
            a["event_id"]: a
            for a in causation_data.get("causation_assessments", [])
            if isinstance(a, dict) and a.get("event_id") in valid_ids
        }
        annotated = 0
        for evt in events:
            if evt.event_id in causation_by_id:
                assessment = causation_by_id[evt.event_id]
                evt.extensions["llm_causal_nexus"] = assessment.get("causal_nexus_score")
                evt.extensions["llm_causal_chain"] = assessment.get("causal_chain")
                annotated += 1
        logger.info(f"LLM Step 19: Annotated {annotated} events with causal scores")

        extensions["llm_metadata"] = {
            "model": model_name,
            "events_analyzed": len(event_rows),
            "run_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "causation_count": len(causation_data.get("causation_assessments", [])),
            "contradiction_count": len(contradiction_data.get("contradiction_flags", [])),
            "vulnerability_count": len(contradiction_data.get("defense_vulnerabilities", [])),
        }

    except json.JSONDecodeError as exc:
        warnings.append(Warning(
            code="LLM_PARSE_ERROR",
            message=f"LLM response was not valid JSON: {exc}",
        ))
        logger.warning(f"LLM Step 19: JSON parse error: {exc}")

    except Exception as exc:
        warnings.append(Warning(
            code="LLM_ERROR",
            message=f"LLM reasoning failed: {type(exc).__name__}: {str(exc)[:200]}",
        ))
        logger.warning(f"LLM Step 19: Unexpected error: {exc}", exc_info=True)

    return extensions, warnings
