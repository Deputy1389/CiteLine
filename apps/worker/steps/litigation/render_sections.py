from __future__ import annotations

import re

from reportlab.platypus import Paragraph, Spacer
from reportlab.lib.units import inch

from apps.worker.lib.claim_ledger_lite import (
    build_claim_ledger_lite,
    depo_safe_rewrite,
    select_top_claim_rows,
    summarize_risk_flags,
)
from apps.worker.steps.case_collapse import (
    build_case_collapse_candidates,
    build_defense_attack_paths,
    build_objection_profiles,
    build_upgrade_recommendations,
    defense_narrative_for_candidate,
    quote_lock,
)
from apps.worker.steps.events.report_quality import sanitize_for_report
from apps.worker.steps.litigation.contradiction_matrix import build_contradiction_matrix
from apps.worker.steps.litigation.narrative_duality import build_narrative_duality


def _sanitize_citation_display(citation: str) -> str:
    cleaned = re.sub(r"\s*\.\s*(pdf|PDF)\b", r".\1", citation or "")
    cleaned = re.sub(r"\s+", " ", cleaned).replace("\n", " ").strip()
    return cleaned


def append_litigation_sections(
    story: list,
    styles,
    projection_entries: list,
    *,
    raw_events: list | None = None,
    missing_records_payload: dict | None = None,
) -> None:
    if not projection_entries:
        return

    claim_rows = build_claim_ledger_lite(projection_entries, raw_events=raw_events)
    story.append(Paragraph("Record-Quote Lock Summary", styles["Heading3"]))
    strong_types = {"PROCEDURE", "IMAGING_FINDING", "INJURY_DX", "WORK_RESTRICTION", "MEDICATION_CHANGE", "GAP_IN_CARE"}
    strongest = [
        r
        for r in select_top_claim_rows(claim_rows, limit=12)
        if str(r.get("claim_type") or "") in strong_types and str(r.get("date") or "").lower() != "unknown"
    ]
    quote_lock_rows = 0
    for item in strongest[:6]:
        cite = _sanitize_citation_display(str(item.get("citation", "") or ""))
        if not cite:
            continue
        narrative = depo_safe_rewrite(str(item.get("assertion") or ""), [item])
        if not narrative:
            continue
        if re.search(r"\b(risks?:|alternatives?:|i,\s*the undersigned|consent to the performance)\b", narrative, re.IGNORECASE):
            continue
        quote = quote_lock(narrative)
        if not quote:
            continue
        line = sanitize_for_report(f"• {item.get('date', 'Date not documented')}: {quote} | Citation(s): {cite}")
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            story.append(Paragraph(line, styles["Normal"]))
            quote_lock_rows += 1
    if quote_lock_rows == 0:
        story.append(Paragraph("No high-signal quote-locked assertions detected.", styles["Normal"]))

    collapse_candidates = build_case_collapse_candidates(claim_rows)
    collapse_candidates_material = [c for c in collapse_candidates if int(c.get("fragility_score") or 0) >= 10]
    story.append(Spacer(1, 0.12 * inch))
    story.append(Paragraph("Case Structural Risk Summary", styles["Heading3"]))
    if collapse_candidates_material:
        primary = collapse_candidates_material[0]
        cits = " | ".join(primary.get("citations", [])[:3])
        weak_link = str(primary.get("fragility_type") or "").replace("_", " ").title()
        why = quote_lock(str(primary.get("why") or "Record structure indicates a vulnerable link."))
        story.append(Paragraph(sanitize_for_report(f"Primary Weak Link: {weak_link}"), styles["Normal"]))
        story.append(Paragraph(sanitize_for_report(f"Why It Matters: {why}"), styles["Normal"]))
        story.append(
            Paragraph(
                sanitize_for_report(f"Defense Narrative Path: {quote_lock(defense_narrative_for_candidate(primary))}"),
                styles["Normal"],
            )
        )
        story.append(Paragraph(sanitize_for_report(f"Citation(s): {cits}"), styles["Normal"]))
    else:
        story.append(Paragraph("Insufficient evidence to rank structural weak links with confidence.", styles["Normal"]))

    defense_paths = build_defense_attack_paths(collapse_candidates_material, limit=3)
    story.append(Spacer(1, 0.1 * inch))
    story.append(Paragraph("Defense Attack Paths (Medical-Only)", styles["Heading3"]))
    if defense_paths:
        for card in defense_paths:
            cits = " | ".join(card.get("citations", [])[:3])
            path_text = quote_lock(str(card.get("path") or ""))
            line = sanitize_for_report(
                f"• {card.get('attack')}: {path_text} | Confidence: {card.get('confidence_tier')} | Citation(s): {cits}"
            )
            story.append(Paragraph(re.sub(r"\s+", " ", line).strip(), styles["Normal"]))
    else:
        story.append(Paragraph("No material defense attack paths identified.", styles["Normal"]))

    upgrades = build_upgrade_recommendations(collapse_candidates_material, limit=4)
    story.append(Spacer(1, 0.1 * inch))
    story.append(Paragraph("Evidence Needed to Strengthen Medical Chain", styles["Heading3"]))
    if upgrades:
        for rec in upgrades:
            cits = " | ".join(rec.get("citations", [])[:3])
            actions = rec.get("actions", [])[:2]
            story.append(Paragraph(sanitize_for_report(f"• Weak Link: {rec.get('weak_link')}"), styles["Normal"]))
            for act in actions:
                story.append(Paragraph(sanitize_for_report(f"  - {act}"), styles["Normal"]))
            if cits:
                story.append(Paragraph(sanitize_for_report(f"  Citation(s): {cits}"), styles["Normal"]))
    else:
        story.append(Paragraph("No targeted evidence upgrades identified.", styles["Normal"]))

    objection_profiles = build_objection_profiles(claim_rows, limit=6)
    story.append(Spacer(1, 0.1 * inch))
    story.append(Paragraph("Objection Anticipation (Deterministic)", styles["Heading3"]))
    if objection_profiles:
        for obj in objection_profiles:
            cats = ", ".join(obj.get("objection_types", []))
            reqs = obj.get("foundation_requirements", [])[:2]
            cits = " | ".join(obj.get("citations", [])[:3])
            line = sanitize_for_report(
                f"• {obj.get('date', 'Date not documented')} | {obj.get('claim_type', 'Claim')} | Objection Risk: {cats}"
            )
            story.append(Paragraph(re.sub(r"\s+", " ", line).strip(), styles["Normal"]))
            for req in reqs:
                story.append(Paragraph(sanitize_for_report(f"  - Foundation Needed: {req}"), styles["Normal"]))
            if cits:
                story.append(Paragraph(sanitize_for_report(f"  Citation(s): {cits}"), styles["Normal"]))
    else:
        story.append(Paragraph("No material objection-risk claims identified.", styles["Normal"]))

    top_requests = list((missing_records_payload or {}).get("priority_requests_top3") or [])
    story.append(Spacer(1, 0.1 * inch))
    story.append(Paragraph("Highest-Value Missing Records To Request", styles["Heading3"]))
    if top_requests:
        for req in top_requests[:3]:
            dfrom = str(((req.get("date_range") or {}).get("from") or ""))
            dto = str(((req.get("date_range") or {}).get("to") or ""))
            line = sanitize_for_report(
                f"• #{req.get('rank', '?')} {req.get('provider_display_name', 'Any provider')} "
                f"| {dfrom} to {dto} | Priority: {req.get('priority_tier', 'Medium')} ({req.get('priority_score', 0)})"
            )
            story.append(Paragraph(re.sub(r"\s+", " ", line).strip(), styles["Normal"]))
            story.append(Paragraph(sanitize_for_report(f"  - Why: {req.get('rationale', '')}"), styles["Normal"]))
    else:
        story.append(Paragraph("No high-priority missing record requests identified.", styles["Normal"]))

    contradiction_rows = build_contradiction_matrix(claim_rows, window_days=45)
    story.append(Spacer(1, 0.1 * inch))
    story.append(Paragraph("Medical Contradiction Matrix", styles["Heading3"]))
    if contradiction_rows:
        for row in contradiction_rows[:6]:
            s = row.get("supporting") or {}
            c = row.get("contradicting") or {}
            category = str(row.get("category") or "").replace("_", " ").title()
            line = (
                f"• {category} | Supporting: {s.get('value')} ({s.get('date')}) "
                f"vs Contradicting: {c.get('value')} ({c.get('date')}) "
                f"| Strength Delta: {row.get('strength_delta')}"
            )
            story.append(Paragraph(sanitize_for_report(line), styles["Normal"]))
            cits = " | ".join((s.get("citations") or [])[:1] + (c.get("citations") or [])[:1])
            if cits:
                story.append(Paragraph(sanitize_for_report(f"  Citation(s): {cits}"), styles["Normal"]))
    else:
        story.append(Paragraph("No material contradictions detected in citation-anchored claims.", styles["Normal"]))

    duality = build_narrative_duality(claim_rows)
    story.append(Spacer(1, 0.1 * inch))
    story.append(Paragraph("Narrative Duality (Deterministic)", styles["Heading3"]))
    plaintiff = (duality.get("plaintiff_narrative") or {}).get("points") or []
    defense = (duality.get("defense_narrative") or {}).get("points") or []
    if plaintiff:
        story.append(Paragraph("Plaintiff Narrative (Strongest Medical Chain)", styles["Normal"]))
        for p in plaintiff[:4]:
            cits = " | ".join((p.get("citations") or [])[:2])
            story.append(
                Paragraph(
                    sanitize_for_report(f"• {p.get('date', 'Date not documented')}: {quote_lock(str(p.get('assertion') or ''))} | Citation(s): {cits}"),
                    styles["Normal"],
                )
            )
    if defense:
        story.append(Paragraph("Defense Narrative (Strongest Competing Chain)", styles["Normal"]))
        for d in defense[:4]:
            cits = " | ".join((d.get("citations") or [])[:2])
            story.append(
                Paragraph(
                    sanitize_for_report(f"• {d.get('attack', 'Competing path')}: {quote_lock(str(d.get('path') or ''))} | Citation(s): {cits}"),
                    styles["Normal"],
                )
            )

    risk_items = summarize_risk_flags(claim_rows)
    if risk_items:
        story.append(Spacer(1, 0.12 * inch))
        story.append(Paragraph("Medical Risk Flags", styles["Heading3"]))
        for item in risk_items:
            line = sanitize_for_report(f"• {item}")
            line = re.sub(r"\s+", " ", line).strip()
            if line:
                story.append(Paragraph(line, styles["Normal"]))
