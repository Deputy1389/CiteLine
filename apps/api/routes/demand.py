"""
API route: Demand narrative generation and draft persistence (Pass 055).

Architecture: LLM is a narrative formatter only. It receives structured,
citation-keyed facts extracted by the pipeline. It never sees raw PDFs and
makes no clinical determinations.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from apps.api.authz import RequestIdentity, assert_firm_access, get_request_identity
from packages.db.database import get_db
from packages.db.models import Artifact, DraftDemand, Matter, Run
from packages.shared.storage import get_artifact_path

logger = logging.getLogger("linecite.demand")
router = APIRouter(tags=["demand"])

SECTION_KEYS = ("liability", "injuries", "treatment", "specials", "demand_amount")
TONES = ("aggressive", "moderate", "conservative")

TONE_GUIDANCE = {
    "aggressive": "Write assertively. Emphasize severity and defendant's culpability. Use strong language appropriate for litigation.",
    "moderate": "Write professionally and factually. Present evidence clearly without embellishment. Balanced tone appropriate for pre-litigation negotiation.",
    "conservative": "Write conservatively. Focus on documented facts only. Understated tone appropriate for early settlement discussions.",
}


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class DemandSection(BaseModel):
    text: str
    citations: list[str]  # citation_ids from the evidence graph


class DraftSections(BaseModel):
    liability: DemandSection | None = None
    injuries: DemandSection | None = None
    treatment: DemandSection | None = None
    specials: DemandSection | None = None
    demand_amount: DemandSection | None = None


class GenerateRequest(BaseModel):
    run_id: str
    tone: str = "moderate"
    section: str | None = None  # None = regenerate all; one of SECTION_KEYS = regen just that section


class GenerateResponse(BaseModel):
    draft_id: str
    sections: DraftSections


class DraftResponse(BaseModel):
    id: str
    case_id: str
    run_id: str
    sections: DraftSections
    tone: str
    created_at: str
    updated_at: str


class PatchSectionRequest(BaseModel):
    section: str
    text: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_evidence_graph(run_id: str) -> dict[str, Any]:
    path = get_artifact_path(run_id, "evidence_graph.json")
    if not path:
        raise HTTPException(status_code=404, detail="evidence_graph.json not found for this run")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _extract_context(graph: dict[str, Any]) -> dict[str, Any]:
    """Pull the structured sections needed for demand generation."""
    inner = graph.get("evidence_graph", graph)
    ext = inner.get("extensions") or graph.get("extensions") or {}

    citations_raw = inner.get("citations") or graph.get("citations") or []
    citation_map = {
        str(c.get("citation_id", "")): {
            "id": str(c.get("citation_id", "")),
            "page": int(c.get("page_number", 0)),
            "snippet": str(c.get("snippet", ""))[:200] if c.get("snippet") else "",
        }
        for c in citations_raw
        if c.get("citation_id")
    }

    return {
        "injury_clusters": ext.get("injury_clusters") or [],
        "cluster_severity": ext.get("injury_cluster_severity") or [],
        "diagnosis_registry": ext.get("diagnosis_registry") or [],
        "causation_timeline": ext.get("causation_timeline_registry") or {},
        "escalation_path": ext.get("treatment_escalation_path") or [],
        "settlement_leverage": ext.get("settlement_leverage_model") or {},
        "settlement_report": ext.get("settlement_model_report") or {},
        "case_severity": ext.get("case_severity_index") or {},
        "defense_attack_map": ext.get("defense_attack_map") or {},
        "citation_map": citation_map,
        "visit_count": len(ext.get("visit_abstraction_registry") or []),
    }


def _build_prompt(
    ctx: dict[str, Any],
    matter_title: str,
    tone: str,
    section: str | None,
    existing_sections: dict[str, Any] | None,
) -> tuple[str, str]:
    """Build system + user prompt for Claude. Returns (system, user)."""
    tone_guidance = TONE_GUIDANCE.get(tone, TONE_GUIDANCE["moderate"])

    if section:
        section_instruction = (
            f"Generate ONLY the '{section}' section. "
            f"Return JSON: {{\"sections\": {{\"{ section }\": {{\"text\": \"...\", \"citations\": [...]}} }} }}"
        )
    else:
        section_instruction = (
            "Generate ALL five sections: liability, injuries, treatment, specials, demand_amount. "
            "Return JSON: {\"sections\": {\"liability\": {\"text\": \"...\", \"citations\": [...]}, "
            "\"injuries\": {...}, \"treatment\": {...}, \"specials\": {...}, \"demand_amount\": {...}}}"
        )

    system = f"""You are a personal injury attorney drafting a demand letter.

RULES:
1. Write factually — every material claim must reference at least one citation_id from the provided evidence.
2. citations[] must contain only citation_ids that exist in the provided citation_map.
3. Do not speculate or add facts not present in the evidence.
4. {tone_guidance}
5. Return valid JSON only. No markdown, no prose outside the JSON.

SECTION DEFINITIONS:
- liability: Defendant's negligence, breach of duty, causation of the collision/incident
- injuries: All diagnosed injuries with severity, supported by imaging and clinical findings
- treatment: Medical treatment received, escalation pattern, ongoing care
- specials: Economic damages (medical bills). If billing data is unavailable or partial, note clearly.
- demand_amount: Settlement demand with justification referencing severity, specials, and liability exposure

{section_instruction}"""

    user_data = {
        "matter_title": matter_title,
        "tone": tone,
        "generate": section or "all",
        "evidence": {
            "injury_clusters": ctx["injury_clusters"][:20],
            "cluster_severity": ctx["cluster_severity"][:10],
            "diagnosis_registry": ctx["diagnosis_registry"][:30],
            "causation_timeline": ctx["causation_timeline"],
            "escalation_path": ctx["escalation_path"][:10],
            "settlement_leverage": ctx["settlement_leverage"],
            "settlement_report": ctx["settlement_report"],
            "case_severity": ctx["case_severity"],
            "total_visits": ctx["visit_count"],
        },
        "citation_map": dict(list(ctx["citation_map"].items())[:100]),
    }

    user = json.dumps(user_data, default=str)
    return system, user


def _call_claude(system: str, user: str) -> dict[str, Any]:
    """Call Claude Sonnet and return parsed JSON response."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="Demand generation requires ANTHROPIC_API_KEY to be configured on the server.",
        )

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        raw_text = message.content[0].text.strip()
        # Strip markdown code fences if present
        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]
        return json.loads(raw_text)
    except json.JSONDecodeError as e:
        logger.error("Claude returned non-JSON: %s", e)
        raise HTTPException(status_code=502, detail="LLM returned malformed response. Please retry.")
    except Exception as e:
        logger.error("Claude API error: %s", e)
        raise HTTPException(status_code=502, detail=f"LLM call failed: {type(e).__name__}")


def _validate_and_clean_sections(
    raw_sections: dict[str, Any],
    citation_map: dict[str, Any],
    target_section: str | None,
) -> dict[str, dict[str, Any]]:
    """Ensure every section has text and at least one valid citation_id.
    Strips invalid citation IDs silently. Raises 422 if a section has no valid citations at all.
    """
    keys = [target_section] if target_section else list(SECTION_KEYS)
    result: dict[str, dict[str, Any]] = {}
    for key in keys:
        raw = raw_sections.get(key) or {}
        text = str(raw.get("text", "")).strip()
        raw_cids = [str(c) for c in (raw.get("citations") or []) if c]
        valid_cids = [cid for cid in raw_cids if cid in citation_map]

        if not text:
            raise HTTPException(
                status_code=422,
                detail=f"LLM returned empty text for section '{key}'. Please retry.",
            )
        if not valid_cids:
            # Invariant: every section must cite at least one real citation.
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Section '{key}' contains no valid citation references. "
                    "Cannot produce an uncited demand narrative section."
                ),
            )
        result[key] = {"text": text, "citations": valid_cids}
    return result


def _upsert_draft(
    db: Session,
    case_id: str,
    run_id: str,
    new_sections: dict[str, dict[str, Any]],
    tone: str,
    existing_draft: DraftDemand | None,
) -> DraftDemand:
    """Merge new sections into existing draft or create one. Returns the saved draft."""
    if existing_draft:
        current = dict(existing_draft.sections or {})
        current.update(new_sections)
        existing_draft.sections = current
        existing_draft.tone = tone
        db.flush()
        return existing_draft
    else:
        draft = DraftDemand(
            id=uuid.uuid4().hex,
            case_id=case_id,
            run_id=run_id,
            sections=new_sections,
            tone=tone,
        )
        db.add(draft)
        db.flush()
        return draft


def _draft_to_response(draft: DraftDemand) -> DraftResponse:
    raw = draft.sections or {}
    sections = DraftSections(
        liability=DemandSection(**raw["liability"]) if "liability" in raw else None,
        injuries=DemandSection(**raw["injuries"]) if "injuries" in raw else None,
        treatment=DemandSection(**raw["treatment"]) if "treatment" in raw else None,
        specials=DemandSection(**raw["specials"]) if "specials" in raw else None,
        demand_amount=DemandSection(**raw["demand_amount"]) if "demand_amount" in raw else None,
    )
    return DraftResponse(
        id=draft.id,
        case_id=draft.case_id,
        run_id=draft.run_id,
        sections=sections,
        tone=draft.tone,
        created_at=draft.created_at.isoformat() if draft.created_at else "",
        updated_at=draft.updated_at.isoformat() if draft.updated_at else "",
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/matters/{matter_id}/demand-narrative", response_model=GenerateResponse)
def generate_demand_narrative(
    matter_id: str,
    req: GenerateRequest,
    db: Session = Depends(get_db),
    identity: RequestIdentity | None = Depends(get_request_identity),
):
    """Generate or regenerate demand narrative sections for a matter run.

    Pass section=None to generate all five sections.
    Pass section='injuries' (or any other key) to regenerate only that section,
    merging the result into the existing draft without touching other sections.
    """
    matter = db.query(Matter).filter_by(id=matter_id).first()
    if not matter:
        raise HTTPException(status_code=404, detail="Matter not found")
    assert_firm_access(identity, matter.firm_id)

    run = db.query(Run).filter_by(id=req.run_id, matter_id=matter_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found for this matter")

    tone = req.tone if req.tone in TONES else "moderate"
    section = req.section if req.section in SECTION_KEYS else None

    # Load evidence graph
    graph = _load_evidence_graph(req.run_id)
    ctx = _extract_context(graph)

    # Find existing draft (for merge on single-section regen)
    existing_draft = (
        db.query(DraftDemand)
        .filter_by(case_id=matter_id, run_id=req.run_id)
        .order_by(DraftDemand.created_at.desc())
        .first()
    )

    # Build prompt and call Claude (retry once on citation validation failure)
    system, user = _build_prompt(ctx, matter.title, tone, section, existing_draft)
    raw_response = _call_claude(system, user)
    raw_sections = (raw_response.get("sections") or raw_response) if isinstance(raw_response, dict) else {}

    new_sections = _validate_and_clean_sections(raw_sections, ctx["citation_map"], section)

    # Persist
    draft = _upsert_draft(db, matter_id, req.run_id, new_sections, tone, existing_draft)

    # Build response sections (full draft contents)
    all_sections_raw = dict(draft.sections or {})
    response_sections = DraftSections(
        liability=DemandSection(**all_sections_raw["liability"]) if "liability" in all_sections_raw else None,
        injuries=DemandSection(**all_sections_raw["injuries"]) if "injuries" in all_sections_raw else None,
        treatment=DemandSection(**all_sections_raw["treatment"]) if "treatment" in all_sections_raw else None,
        specials=DemandSection(**all_sections_raw["specials"]) if "specials" in all_sections_raw else None,
        demand_amount=DemandSection(**all_sections_raw["demand_amount"]) if "demand_amount" in all_sections_raw else None,
    )

    return GenerateResponse(draft_id=draft.id, sections=response_sections)


@router.get("/matters/{matter_id}/demand-drafts", response_model=list[DraftResponse])
def list_demand_drafts(
    matter_id: str,
    db: Session = Depends(get_db),
    identity: RequestIdentity | None = Depends(get_request_identity),
):
    """List all demand drafts for a matter, newest first."""
    matter = db.query(Matter).filter_by(id=matter_id).first()
    if not matter:
        raise HTTPException(status_code=404, detail="Matter not found")
    assert_firm_access(identity, matter.firm_id)

    drafts = (
        db.query(DraftDemand)
        .filter_by(case_id=matter_id)
        .order_by(DraftDemand.created_at.desc())
        .limit(20)
        .all()
    )
    return [_draft_to_response(d) for d in drafts]


@router.get("/matters/{matter_id}/demand-drafts/{draft_id}", response_model=DraftResponse)
def get_demand_draft(
    matter_id: str,
    draft_id: str,
    db: Session = Depends(get_db),
    identity: RequestIdentity | None = Depends(get_request_identity),
):
    """Load a specific demand draft."""
    matter = db.query(Matter).filter_by(id=matter_id).first()
    if not matter:
        raise HTTPException(status_code=404, detail="Matter not found")
    assert_firm_access(identity, matter.firm_id)

    draft = db.query(DraftDemand).filter_by(id=draft_id, case_id=matter_id).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    return _draft_to_response(draft)


@router.patch("/matters/{matter_id}/demand-drafts/{draft_id}", response_model=DraftResponse)
def patch_demand_draft(
    matter_id: str,
    draft_id: str,
    req: PatchSectionRequest,
    db: Session = Depends(get_db),
    identity: RequestIdentity | None = Depends(get_request_identity),
):
    """Save attorney edits to a single section of a demand draft (auto-save)."""
    matter = db.query(Matter).filter_by(id=matter_id).first()
    if not matter:
        raise HTTPException(status_code=404, detail="Matter not found")
    assert_firm_access(identity, matter.firm_id)

    if req.section not in SECTION_KEYS:
        raise HTTPException(status_code=422, detail=f"Invalid section '{req.section}'")

    draft = db.query(DraftDemand).filter_by(id=draft_id, case_id=matter_id).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    current = dict(draft.sections or {})
    if req.section in current:
        current[req.section] = {**current[req.section], "text": req.text}
    else:
        current[req.section] = {"text": req.text, "citations": []}
    draft.sections = current
    db.flush()

    return _draft_to_response(draft)
