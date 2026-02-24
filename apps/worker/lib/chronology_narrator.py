"""
Chronology Narrator — Modern Google-GenAI
"""
from __future__ import annotations
import json
import logging
import os
from datetime import datetime, timezone, date
from google import genai
from google.genai import types
from packages.shared.models import EvidenceGraph, Provider, RunConfig, NarrativeEntry, NarrativeChronology, Event
from apps.worker.lib.llm_skills_adapter import to_skill_event

logger = logging.getLogger(__name__)

def _compact_event_payload(events: list[Event], providers: list[Provider]) -> list[dict]:
    payload = []
    for e in events:
        summary = " ".join(f.text for f in e.facts[:3])
        payload.append({"event_id": e.event_id, "date": str(e.date.value) if e.date and e.date.value else "Undated", "type": e.event_type.value, "summary": summary[:500]})
    return payload

def generate_anchored_narrative(evidence_graph: EvidenceGraph, providers: list[Provider], config: RunConfig) -> NarrativeChronology:
    candidates = [e for e in evidence_graph.events if e.confidence >= 30 and len(e.citation_ids) >= 1][:100]
    if not candidates: return NarrativeChronology(generated_at=datetime.now(timezone.utc), entries=[])

    if os.getenv("MOCK_LLM") == "true":
        logger.info("MOCK_LLM is true, returning mock narrative.")
        entries = [
            NarrativeEntry(
                row_id="mock_1",
                label="Mock Phase",
                headline="Mock headline for testing.",
                bullets=["Mock bullet 1"],
                event_ids=[candidates[0].event_id],
                citation_ids=candidates[0].citation_ids,
                confidence=1.0
            )
        ]
        return NarrativeChronology(generated_at=datetime.now(timezone.utc), entries=entries, model_name="mock-model")

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key: return NarrativeChronology(generated_at=datetime.now(timezone.utc), entries=[])

    try:
        client = genai.Client(api_key=api_key)
        prompt = f"Compose a chronology from these events. Output JSON matching the schema.\nInput: {json.dumps(_compact_event_payload(candidates, providers))}"
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        
        raw_text = response.text
        if "```json" in raw_text:
            raw_text = raw_text.split("```json")[1].split("```")[0].strip()
        data = json.loads(raw_text)
        
        entries = []
        for i, row in enumerate(data.get("chronology_rows", [])):
            entries.append(NarrativeEntry(
                row_id=f"row_{i}",
                label=row.get("label", "General"),
                headline=row.get("headline", ""),
                bullets=row.get("bullets", []),
                event_ids=row.get("event_ids", []),
                citation_ids=[], # Computed by validator if needed
                confidence=float(row.get("confidence", 0.8))
            ))
        return NarrativeChronology(generated_at=datetime.now(timezone.utc), entries=entries, model_name="gemini-2.0-flash")
    except Exception as exc:
        logger.error(f"Narrator failed: {exc}")
        return NarrativeChronology(generated_at=datetime.now(timezone.utc), entries=[])
