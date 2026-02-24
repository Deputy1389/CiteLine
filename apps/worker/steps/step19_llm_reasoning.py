"""
Step 19 — LLM Reasoning (Gemini Flash)

Optional semantic layer: causation assessment, contradiction detection,
and case summarization via Gemini Flash.

Only runs if config.enable_llm_reasoning is True and GEMINI_API_KEY is set.
All LLM assertions are validated — only references to existing event_ids are kept.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from packages.shared.models import EvidenceGraph, Event, Provider, RunConfig, Warning

logger = logging.getLogger(__name__)

_GEMINI_TIMEOUT = 60  # seconds per request
_MAX_EVENTS_FOR_LLM = 200  # cap payload size
_MAX_FACTS_PER_EVENT = 3   # only top facts per event


def _build_event_payload(events: list[Event], providers: list[Provider]) -> list[dict]:
    """Build compact event summaries for LLM consumption."""
    provider_map = {p.provider_id: p.normalized_name for p in providers}
    rows = []
    for evt in events[:_MAX_EVENTS_FOR_LLM]:
        date_str = evt.date.value.isoformat() if (evt.date and evt.date.value) else "unknown"
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
    events_json = json.dumps(event_rows, indent=2)
    return f"""You are a medical-legal analyst reviewing a personal injury (PI) case.

Analyze the following medical events and assess causal relationships to the initial accident/incident.

Events (JSON):
{events_json}

For each event, assess:
1. causal_nexus_score (0-100):
   - 90-100: Direct causation (injury from accident, acute treatment)
   - 70-89: Strongly related (follow-up care, documented sequelae)
   - 50-69: Probably related (could be related, uncertain)
   - 30-49: Possibly related (pre-existing, coincidental timing)
   - 0-29: Unrelated or unclear

2. causal_chain: Brief description of the causal pathway (max 100 chars)

Also provide:
- case_summary: 2-3 sentence overall case summary
- risk_score: 0-100 overall case strength for plaintiff

IMPORTANT: Only reference event_ids that appear in the input above. Do not invent event_ids.

Respond with valid JSON only:
{{
  "causation_assessments": [
    {{
      "event_id": "<existing event_id>",
      "causal_nexus_score": <0-100>,
      "causal_chain": "<brief description>"
    }}
  ],
  "case_summary": "<2-3 sentence case summary>",
  "risk_score": <0-100>
}}"""


def _prompt_contradictions(event_rows: list[dict]) -> str:
    events_json = json.dumps(event_rows, indent=2)
    return f"""You are a medical-legal analyst reviewing a personal injury (PI) case for potential defense challenges.

Analyze the following medical events and identify:
1. Contradictions between events (inconsistent symptoms, conflicting diagnoses)
2. Suspicious temporal patterns (unexplained gaps, retroactive diagnoses)
3. Documentation issues (missing records, provider inconsistencies)

Events (JSON):
{events_json}

IMPORTANT: Only reference event_ids from the input above. Do not invent event_ids. If a flag applies to a single event, use null for event_id_b.

Respond with valid JSON only:
{{
  "contradiction_flags": [
    {{
      "event_id_a": "<existing event_id or null>",
      "event_id_b": "<existing event_id or null>",
      "contradiction_type": "<TEMPORAL_GAP|SYMPTOM_CONFLICT|DIAGNOSIS_CONFLICT|DOCUMENTATION_GAP|OTHER>",
      "severity": "<HIGH|MEDIUM|LOW>",
      "description": "<brief description max 200 chars>"
    }}
  ],
  "defense_vulnerabilities": [
    {{
      "vulnerability_type": "<GAP_IN_CARE|PRE_EXISTING|INCONSISTENT_HISTORY|DELAYED_TREATMENT|OTHER>",
      "description": "<brief description max 200 chars>",
      "related_event_ids": ["<existing event_id>"]
    }}
  ]
}}"""


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
        import google.generativeai as genai
    except ImportError:
        warnings.append(Warning(
            code="LLM_SKIPPED",
            message="google-generativeai not installed — LLM reasoning skipped",
        ))
        return extensions, warnings

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            model_name=config.gemini_model,
            generation_config={"response_mime_type": "application/json"},
        )

        events = evidence_graph.events
        valid_ids = {e.event_id for e in events}
        event_rows = _build_event_payload(events, providers)

        if not event_rows:
            logger.info("LLM Step 19: No events to analyze — skipping")
            return extensions, warnings

        logger.info(f"LLM Step 19: Starting — {len(event_rows)} events, model={config.gemini_model}")

        # ── Prompt 1: Causation assessment ────────────────────────────────
        t0 = time.time()
        causation_response = model.generate_content(
            _prompt_causation(event_rows),
            request_options={"timeout": _GEMINI_TIMEOUT},
        )
        causation_data = json.loads(causation_response.text)
        causation_data = _validate_event_ids(causation_data, valid_ids)
        extensions["llm_causation"] = causation_data
        logger.info(
            f"LLM Step 19: Causation done in {time.time()-t0:.1f}s — "
            f"{len(causation_data.get('causation_assessments', []))} assessments"
        )

        # ── Prompt 2: Contradictions ───────────────────────────────────────
        t0 = time.time()
        contradiction_response = model.generate_content(
            _prompt_contradictions(event_rows),
            request_options={"timeout": _GEMINI_TIMEOUT},
        )
        contradiction_data = json.loads(contradiction_response.text)
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
            "model": config.gemini_model,
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
