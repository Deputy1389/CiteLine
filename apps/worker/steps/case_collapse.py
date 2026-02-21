from __future__ import annotations

import re
from datetime import date
from typing import Any

from packages.shared.models import ClaimEdge
from packages.shared.utils.claim_utils import parse_iso as _parse_iso
from packages.shared.utils.claim_utils import stable_id as _stable_id

ClaimRowLike = dict[str, Any] | ClaimEdge


def quote_lock(text: str, *, max_len: int = 180) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    # Drop form checkbox markers so checklist artifacts do not leak into client output.
    cleaned = re.sub(r"\[\s*[xX ]\s*\]", "", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    cleaned = cleaned.strip("\" ")
    if not cleaned:
        return ""
    fragment = cleaned[:max_len].rstrip(" .;:")
    return f"\"{fragment}\""


def _collect_citations(rows: list[ClaimRowLike], limit: int = 3) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for c in row.get("citations", []) or []:
            cc = str(c).strip()
            if not cc or cc in seen:
                continue
            seen.add(cc)
            out.append(cc)
            if len(out) >= limit:
                return out
    return out


def _incident_date(claim_rows: list[ClaimRowLike]) -> date | None:
    ed_rows = []
    for r in claim_rows:
        text = str(r.get("assertion") or "").lower()
        if re.search(r"\b(mva|mvc|rear[- ]end|collision|accident|emergency|chief complaint)\b", text):
            ed_rows.append(r)
    dates = [_parse_iso(str(r.get("date") or "")) for r in ed_rows]
    dates = sorted([d for d in dates if d])
    return dates[0] if dates else None


def build_case_collapse_candidates(claim_rows: list[ClaimRowLike]) -> list[dict]:
    incident = _incident_date(claim_rows)
    rows_by_type: dict[str, list[ClaimRowLike]] = {}
    for r in claim_rows:
        rows_by_type.setdefault(str(r.get("claim_type") or ""), []).append(r)

    candidates: list[dict] = []

    pre_rows = rows_by_type.get("PRE_EXISTING_MENTION", [])
    pre_rows = [r for r in pre_rows if "pre_existing_overlap" in (r.get("flags") or [])]
    pre_rows = [r for r in pre_rows if re.search(r"\b(history of|pre-existing|prior|chronic)\b", str(r.get("assertion") or "").lower())]
    if pre_rows:
        pre_score = min(20, 6 + 2 * len(pre_rows))
        if incident:
            dated_pre = []
            for r in pre_rows:
                d = _parse_iso(str(r.get("date") or ""))
                if d and d < incident:
                    dated_pre.append(r)
            if dated_pre:
                pre_rows = dated_pre
                pre_score = min(20, pre_score + 4)
        cits = _collect_citations(pre_rows)
        if len(cits) >= 1 and pre_score >= 6:
            candidates.append(
                {
                    "id": _stable_id(["PRE_EXISTING_OVERLAP", *cits]),
                    "fragility_type": "PRE_EXISTING_OVERLAP",
                    "score_components": {"pre_existing_depth": pre_score},
                    "fragility_score": pre_score,
                    "support_rows": pre_rows[:4],
                    "citations": cits,
                    "why": "Pre-incident/chronic language overlaps body-region complaints.",
                }
            )

    deg_rows = [r for r in claim_rows if "degenerative_language" in (r.get("flags") or [])]
    deg_rows = [r for r in deg_rows if re.search(r"\b(degenerative|chronic|spondylosis|age-related)\b", str(r.get("assertion") or "").lower())]
    if deg_rows:
        deg_score = min(15, 4 + 2 * len(deg_rows))
        cits = _collect_citations(deg_rows)
        if len(cits) >= 1 and deg_score >= 6:
            candidates.append(
                {
                    "id": _stable_id(["DEGENERATIVE_COMPETING_EXPLANATION", *cits]),
                    "fragility_type": "DEGENERATIVE_COMPETING_EXPLANATION",
                    "score_components": {"degenerative_competition": deg_score},
                    "fragility_score": deg_score,
                    "support_rows": deg_rows[:4],
                    "citations": cits,
                    "why": "Degenerative/chronic wording allows a non-traumatic explanation path.",
                }
            )

    gap_rows = rows_by_type.get("GAP_IN_CARE", [])
    if gap_rows:
        max_gap = max(
            [int(re.search(r"\b(\d+)\s+days\b", str(r.get("assertion") or "")) .group(1)) if re.search(r"\b(\d+)\s+days\b", str(r.get("assertion") or "")) else 0 for r in gap_rows],
            default=0,
        )
        gap_score = min(20, max(0, int(max_gap / 6)))
        cits = _collect_citations(gap_rows)
        if len(cits) >= 1 and max_gap >= 45 and gap_score >= 6:
            candidates.append(
                {
                    "id": _stable_id(["GAP_BEFORE_ESCALATION", str(max_gap), *cits]),
                    "fragility_type": "GAP_BEFORE_ESCALATION",
                    "score_components": {"gap_severity": gap_score},
                    "fragility_score": gap_score,
                    "support_rows": gap_rows[:3],
                    "citations": cits,
                    "why": f"Documented treatment gap ({max_gap} days) creates continuity vulnerability.",
                }
            )

    symptom_rows = rows_by_type.get("SYMPTOM", [])
    objective_rows = rows_by_type.get("IMAGING_FINDING", []) + rows_by_type.get("PROCEDURE", [])
    if len(symptom_rows) >= 4:
        deficit = max(0, len(symptom_rows) - len(objective_rows))
        objective_deficit = min(20, 2 * deficit)
        cits = _collect_citations(symptom_rows)
        if len(cits) >= 1 and objective_deficit >= 6:
            candidates.append(
                {
                    "id": _stable_id(["LOW_OBJECTIVE_CORROBORATION", *cits]),
                    "fragility_type": "LOW_OBJECTIVE_CORROBORATION",
                    "score_components": {"objective_corroboration_deficit": objective_deficit},
                    "fragility_score": objective_deficit,
                    "support_rows": symptom_rows[:4],
                    "citations": cits,
                    "why": "Symptom density exceeds objective corroboration density.",
                }
            )

    incons_rows = [r for r in claim_rows if "laterality_conflict" in (r.get("flags") or [])]
    if incons_rows:
        incons_score = min(15, 6 + 3 * len(incons_rows))
        cits = _collect_citations(incons_rows)
        if len(cits) >= 1 and incons_score >= 6:
            candidates.append(
                {
                    "id": _stable_id(["SYMPTOM_INCONSISTENCY", *cits]),
                    "fragility_type": "SYMPTOM_INCONSISTENCY",
                    "score_components": {"inconsistency_density": incons_score},
                    "fragility_score": incons_score,
                    "support_rows": incons_rows[:4],
                    "citations": cits,
                    "why": "Inconsistent laterality/symptom positioning appears in clinical record.",
                }
            )

    # Global mitigation offsets to keep the model conservative.
    acute_markers = 0
    if incident is not None:
        acute_markers += 1
    if objective_rows:
        acute_markers += 1
    if any("mva" in str(r.get("assertion") or "").lower() or "mvc" in str(r.get("assertion") or "").lower() for r in symptom_rows):
        acute_markers += 1

    for c in candidates:
        score = int(c.get("fragility_score") or 0)
        # Mitigate fragility when objective/acute chain exists.
        mitigation = min(6, acute_markers * 2)
        if str(c.get("fragility_type") or "") == "LOW_OBJECTIVE_CORROBORATION":
            # If objective rows are at/above symptom density, suppress this candidate.
            if len(objective_rows) >= len(symptom_rows):
                score = 0
            else:
                score = max(0, score - mitigation)
        else:
            score = max(0, score - max(0, mitigation - 2))
        c["fragility_score"] = score
        c.setdefault("score_components", {})
        c["score_components"]["acute_marker_strength"] = -mitigation
        if score >= 18:
            tier = "High"
        elif score >= 10:
            tier = "Medium"
        else:
            tier = "Low"
        c["confidence_tier"] = tier
        c["incident_date"] = incident.isoformat() if incident else None

    candidates.sort(key=lambda c: (-int(c.get("fragility_score") or 0), str(c.get("fragility_type") or ""), str(c.get("id") or "")))
    # Conservative suppression to keep false positives low.
    return [c for c in candidates if int(c.get("fragility_score") or 0) >= 5]


def build_defense_attack_paths(candidates: list[dict], *, limit: int = 3) -> list[dict]:
    out: list[dict] = []
    for c in candidates:
        if int(c.get("fragility_score") or 0) < 6:
            continue
        if len(out) >= limit:
            break
        out.append(
            {
                "attack": str(c.get("fragility_type") or "").replace("_", " ").title(),
                "path": str(c.get("why") or ""),
                "confidence_tier": str(c.get("confidence_tier") or "Low"),
                "citations": list(c.get("citations") or [])[:3],
                "score": int(c.get("fragility_score") or 0),
            }
        )
    return out


def build_upgrade_recommendations(candidates: list[dict], *, limit: int = 4) -> list[dict]:
    mapping = {
        "PRE_EXISTING_OVERLAP": [
            "Obtain pre-incident PCP/specialty records to document asymptomatic intervals.",
            "Seek comparative interpretation distinguishing acute aggravation vs baseline condition.",
        ],
        "DEGENERATIVE_COMPETING_EXPLANATION": [
            "Obtain provider statement on acute-on-chronic differentiation tied to timeline.",
            "Add objective comparison showing post-incident change from baseline.",
        ],
        "GAP_BEFORE_ESCALATION": [
            "Document reason for delayed care (access, scheduling, symptom trajectory).",
            "Collect interim records that show continuity of symptoms during gap interval.",
        ],
        "LOW_OBJECTIVE_CORROBORATION": [
            "Add objective exam/imaging anchors linked to symptom region and dates.",
            "Capture specialist findings with measurable functional deficits.",
        ],
        "SYMPTOM_INCONSISTENCY": [
            "Add contemporaneous clarification notes resolving laterality/symptom conflicts.",
            "Anchor with repeated objective exam findings across visits.",
        ],
    }
    out: list[dict] = []
    for c in candidates[:limit]:
        key = str(c.get("fragility_type") or "")
        actions = mapping.get(key, ["Add citation-backed objective records to reduce structural uncertainty."])
        out.append(
            {
                "weak_link": key.replace("_", " ").title(),
                "actions": actions[:2],
                "citations": list(c.get("citations") or [])[:3],
            }
        )
    return out


def build_objection_profiles(claim_rows: list[ClaimRowLike], *, limit: int = 24) -> list[dict]:
    """
    Deterministic evidentiary-objection anticipation for claim rows.
    Categories: foundation, relevance, hearsay, best evidence.
    """
    profiles: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for row in claim_rows:
        claim_id = str(row.get("id") or "")
        claim_type = str(row.get("claim_type") or "")
        assertion = str(row.get("assertion") or "").strip()
        if not assertion:
            continue
        citations = [str(c).strip() for c in (row.get("citations") or []) if str(c).strip()]
        support_score = int(row.get("support_score") or 0)
        support_strength = str(row.get("support_strength") or "Weak")
        flags = {str(f) for f in (row.get("flags") or [])}
        low = assertion.lower()

        objection_types: list[str] = []
        foundation_reqs: list[str] = []
        objection_reasons: list[str] = []

        # Foundation: unsupported or ambiguous claims.
        if not citations or support_score < 3 or "timing_ambiguous" in flags:
            objection_types.append("foundation")
            if not citations:
                foundation_reqs.append("Attach at least one page-level citation for this assertion.")
                objection_reasons.append("No citation anchor attached.")
            if support_score < 3:
                foundation_reqs.append("Add objective corroboration (imaging/procedure/assessment).")
                objection_reasons.append("Low deterministic support score.")
            if "timing_ambiguous" in flags:
                foundation_reqs.append("Resolve event date from source note header/body.")
                objection_reasons.append("Date is ambiguous.")

        # Hearsay: subjective reports without objective corroboration.
        if re.search(r"\b(patient reports|reports|states|complains of|subjective)\b", low):
            if claim_type in {"SYMPTOM", "TREATMENT_VISIT"} and support_score < 6:
                objection_types.append("hearsay")
                foundation_reqs.append("Pair subjective report with provider assessment or objective finding.")
                objection_reasons.append("Assertion is primarily subjective report language.")

        # Best evidence: references to results/procedures without strong documentary anchor.
        if re.search(r"\b(mri|ct|x-?ray|impression|procedure|injection|surgery)\b", low):
            has_page_anchor = any(re.search(r"\bp\.\s*\d+\b", c.lower()) for c in citations)
            if not has_page_anchor or support_score < 4:
                objection_types.append("best_evidence")
                foundation_reqs.append("Provide direct report-page citation for imaging/procedure source.")
                objection_reasons.append("Result/procedure claim lacks strong source-page anchor.")

        # Relevance: low-materiality routine rows in topline narrative.
        if claim_type in {"TREATMENT_VISIT", "SYMPTOM"} and support_score <= 2:
            objection_types.append("relevance")
            foundation_reqs.append("Tie to functional change, escalation, or diagnosis context.")
            objection_reasons.append("Low materiality row may be challenged as cumulative.")

        if not objection_types:
            continue

        dedupe_key = (
            str(row.get("date") or "unknown"),
            claim_type,
            re.sub(r"\W+", " ", low).strip()[:120],
        )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        profiles.append(
            {
                "claim_id": claim_id,
                "event_id": str(row.get("event_id") or ""),
                "date": str(row.get("date") or "unknown"),
                "claim_type": claim_type,
                "assertion": assertion,
                "support_score": support_score,
                "support_strength": support_strength,
                "objection_types": sorted(set(objection_types)),
                "objection_reasons": sorted(set(objection_reasons)),
                "foundation_requirements": sorted(set(foundation_reqs)),
                "citations": citations[:3],
            }
        )

        if len(profiles) >= limit:
            break

    profiles.sort(
        key=lambda p: (
            -len(p.get("objection_types") or []),
            int(p.get("support_score") or 0),
            str(p.get("date") or ""),
            str(p.get("claim_id") or ""),
        )
    )
    return profiles


def defense_narrative_for_candidate(candidate: dict) -> str:
    fragility = str(candidate.get("fragility_type") or "")
    mapping = {
        "PRE_EXISTING_OVERLAP": "Symptoms may reflect continuation/aggravation of pre-existing condition history.",
        "DEGENERATIVE_COMPETING_EXPLANATION": "Findings may be interpreted as chronic/degenerative rather than acute-only change.",
        "GAP_BEFORE_ESCALATION": "Delay in documented care may weaken continuity of acute symptom progression.",
        "LOW_OBJECTIVE_CORROBORATION": "Subjective symptom burden may exceed objective corroboration density.",
        "SYMPTOM_INCONSISTENCY": "Inconsistent symptom patterning may support a competing interpretation path.",
    }
    return mapping.get(fragility, "Competing medical interpretation may be argued from available record structure.")
