from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TOOL_VERSION = "qa-litigation-1.0"
TARGET_SCORE = 98
MIN_TIMELINE_CITATION_COVERAGE = 0.95
MAX_VITALS_PRO_RATIO = 0.10
MAX_ADMIN_RATIO = 0.05

PROVIDER_CONTAMINATION_TOKENS = (
    "stress test",
    "synthea",
    "1000 page",
    "medical record summary",
    "chronology eval",
    "sample 172",
)
QUESTIONNAIRE_MARKERS = ("phq-9", "gad-7", "questionnaire", "survey score", "pain interference", "promis")
VITALS_MARKERS = ("blood pressure", "heart rate", "respiratory rate", "body weight", "body height", "bmi", "temperature", "pulse")
ADMIN_MARKERS = ("administrative", "record index", "cover sheet")
ABNORMAL_LAB_RE = re.compile(r"\b(h|l|high|low|critical|panic|elevated|depressed|abnormal|>|<)\b", re.IGNORECASE)
PRO_RE = re.compile(r"\b(phq-?9|gad-?7|promis|pain interference|pain intensity|pain severity|what number best describes)\b", re.IGNORECASE)
DX_APPENDIX_CONTAM_RE = re.compile(
    r"appendix b: diagnoses/problems[\s\S]{0,2000}(hospital admission|emergency room admission|general examination of patient|encounter:)",
    re.IGNORECASE,
)
ISO_TS_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})t\d{2}:\d{2}:\d{2}z\b", re.IGNORECASE)
INPATIENT_MARKER_RE = re.compile(r"\b(admission order|hospital day|inpatient service|discharge summary|admitted|inpatient|hospitalist|icu)\b", re.IGNORECASE)
MECHANISM_RE = re.compile(r"\b(mva|mvc|motor vehicle|rear[- ]end|collision|accident|fell|fall|slipped)\b", re.IGNORECASE)
PROCEDURE_ANCHOR_RE = re.compile(r"\b(depo-?medrol|lidocaine|fluoroscopy|interlaminar|transforaminal|epidural steroid injection|esi)\b", re.IGNORECASE)
DX_GIBBERISH_RE = re.compile(r"\b(difficult mission late kind|lorem ipsum|asdf|qwerty)\b", re.IGNORECASE)


@dataclass
class Anchor:
    page_number: int
    snippet_hash: str
    confidence: float = 0.85

    def as_dict(self) -> dict[str, Any]:
        return {"page_number": self.page_number, "snippet_hash": self.snippet_hash, "confidence": self.confidence}


def _hash_snippet(snippet: str) -> str:
    return hashlib.sha256(snippet.encode("utf-8")).hexdigest()[:16]


def _extract_summary_field(report_text: str, field: str) -> str | None:
    m = re.search(rf"(?im)^\s*{re.escape(field)}\s*:\s*(.+?)\s*$", report_text)
    if not m:
        return None
    value = m.group(1).strip()
    if value.lower() in {
        "not established from records",
        "not stated in records",
        "unable to determine from provided records",
        "unknown",
        "none documented",
    }:
        return None
    return value


def _find_anchors(page_text_by_number: dict[int, str], patterns: list[str], min_anchors: int) -> list[Anchor]:
    anchors: list[Anchor] = []
    for page in sorted(page_text_by_number.keys()):
        text = page_text_by_number.get(page, "")
        if not text:
            continue
        low = text.lower()
        if all(re.search(pat, low, re.IGNORECASE) for pat in patterns):
            anchors.append(Anchor(page_number=page, snippet_hash=_hash_snippet(text[:500])))
    return anchors[: max(min_anchors, 5)]


def _issue(code: str, message: str, evidence_refs: list[Any] | None = None) -> dict[str, Any]:
    return {"code": code, "message": message, "evidence_refs": evidence_refs or []}


def build_litigation_checklist(
    *,
    run_id: str,
    source_pdf: str,
    report_text: str,
    ctx: dict[str, Any],
    chronology_pdf_path: Path | None = None,
    chronology_json_path: Path | None = None,
) -> dict[str, Any]:
    projection_entries = list(ctx.get("projection_entries", []))
    events = list(ctx.get("events", []))
    missing = ctx.get("missing_records_payload", {}) or {}
    page_text_by_number = ctx.get("page_text_by_number", {}) or {}
    source_pages = int(ctx.get("source_pages", 0) or 0)
    lower_report = report_text.lower()

    hard_invariants: dict[str, dict[str, Any]] = {
        "H1_no_fabricated_high_risk_claims": {"pass": True, "details": []},
        "H2_patient_boundary_integrity": {"pass": True, "details": []},
        "H3_no_unknown_patient_in_core": {"pass": True, "details": []},
        "H4_citations_present_on_timeline_rows": {"pass": True, "details": []},
        "H5_temporal_sanity": {"pass": True, "details": []},
        "H6_provider_facility_contamination": {"pass": True, "details": []},
        "H7_determinism_placeholder": {"pass": True, "details": []},
        "H8_output_contract": {"pass": True, "details": []},
    }
    quality_gates: dict[str, dict[str, Any]] = {
        "Q1_substance_ratio": {"pass": True, "metrics": {}, "details": []},
        "Q2_coverage_floor": {"pass": True, "metrics": {}, "details": []},
        "Q3_med_change_semantics_sanity": {"pass": True, "metrics": {}, "details": []},
        "Q4_gap_anchoring": {"pass": True, "metrics": {}, "details": []},
        "Q5_dx_problem_purity": {"pass": True, "metrics": {}, "details": []},
        "Q6_pro_detection_consistency": {"pass": True, "metrics": {}, "details": []},
        "Q7_sdoh_quarantine_no_leak": {"pass": True, "metrics": {}, "details": []},
        "Q8_attorney_usability_sections": {"pass": True, "metrics": {}, "details": []},
        "Q_SEM_1_encounter_type_sanity": {"pass": True, "metrics": {}, "details": []},
        "Q_SEM_2_mechanism_required_when_present": {"pass": True, "metrics": {}, "details": []},
        "Q_SEM_3_procedure_specificity_when_anchors_present": {"pass": True, "metrics": {}, "details": []},
        "Q_SEM_4_dx_purity": {"pass": True, "metrics": {}, "details": []},
        "Q_SEM_5_date_drift": {"pass": True, "metrics": {}, "details": []},
        "Q_USE_1_required_buckets_present": {"pass": True, "metrics": {}, "details": []},
        "Q_USE_2_min_substantive_rows": {"pass": True, "metrics": {}, "details": []},
        "Q_USE_3_imaging_impression_present": {"pass": True, "metrics": {}, "details": []},
        "Q_USE_4_no_noise_gibberish": {"pass": True, "metrics": {}, "details": []},
        "Q_USE_5_no_placeholder_language": {"pass": True, "metrics": {}, "details": []},
        "Q_USE_HIGH_DENSITY_RATIO": {"pass": True, "metrics": {}, "details": []},
        "Q_USE_NO_FLOW_NOISE_EVENTS": {"pass": True, "metrics": {}, "details": []},
        "Q_USE_NO_TEMPLATE_LANGUAGE": {"pass": True, "metrics": {}, "details": []},
        "Q_USE_VERBATIM_SNIPPETS": {"pass": True, "metrics": {}, "details": []},
        "Q_USE_EXTRACTION_SUFFICIENCY": {"pass": True, "metrics": {}, "details": []},
        "Q_USE_NO_META_LANGUAGE": {"pass": True, "metrics": {}, "details": []},
        "Q_USE_DIRECT_SNIPPET_REQUIRED": {"pass": True, "metrics": {}, "details": []},
        "Q_FINAL_RENDER_CONSISTENCY": {"pass": True, "metrics": {}, "details": []},
    }

    # H2
    patient_scope_violations = list(ctx.get("patient_scope_violations", []))
    if patient_scope_violations:
        issue = _issue("PATIENT_LEAKAGE", f"{len(patient_scope_violations)} patient scope violations detected.", patient_scope_violations[:5])
        hard_invariants["H2_patient_boundary_integrity"]["pass"] = False
        hard_invariants["H2_patient_boundary_integrity"]["details"].append(issue)
    if any((e.extensions or {}).get("patient_scope_id") in (None, "") for e in events):
        issue = _issue("PATIENT_LEAKAGE", "One or more events missing patient_scope_id.")
        hard_invariants["H2_patient_boundary_integrity"]["pass"] = False
        hard_invariants["H2_patient_boundary_integrity"]["details"].append(issue)

    # H3
    unknown_timeline = [e.event_id for e in projection_entries if getattr(e, "patient_label", "") == "Unknown Patient"]
    if unknown_timeline:
        issue = _issue("UNKNOWN_PATIENT_CORE", "Unknown Patient row(s) found in timeline.", unknown_timeline[:10])
        hard_invariants["H3_no_unknown_patient_in_core"]["pass"] = False
        hard_invariants["H3_no_unknown_patient_in_core"]["details"].append(issue)
    unknown_gap = [g.get("gap_id") for g in missing.get("gaps", []) if g.get("patient_scope_id") in (None, "", "ps_unknown")]
    if unknown_gap:
        issue = _issue("UNKNOWN_PATIENT_CORE", "Unknown/unscoped patient gap(s) found.", unknown_gap[:10])
        hard_invariants["H3_no_unknown_patient_in_core"]["pass"] = False
        hard_invariants["H3_no_unknown_patient_in_core"]["details"].append(issue)

    # H6
    contaminated = []
    for entry in projection_entries:
        provider = (getattr(entry, "provider_display", "") or "").lower()
        if provider and any(tok in provider for tok in PROVIDER_CONTAMINATION_TOKENS):
            contaminated.append({"event_id": entry.event_id, "provider_display": entry.provider_display})
    if contaminated:
        issue = _issue("PROVIDER_CONTAMINATION", "Provider/facility field contains document/run label contamination.", contaminated[:10])
        hard_invariants["H6_provider_facility_contamination"]["pass"] = False
        hard_invariants["H6_provider_facility_contamination"]["details"].append(issue)

    # H1
    high_risk_claims: list[dict[str, Any]] = []
    doi = _extract_summary_field(report_text, "Date of Injury")
    if doi:
        anchors = _find_anchors(page_text_by_number, [re.escape(doi.lower())], min_anchors=1)
        claim = {"type": "doi", "value": doi, "support_anchors": [a.as_dict() for a in anchors]}
        high_risk_claims.append(claim)
        if len(anchors) < 1:
            hard_invariants["H1_no_fabricated_high_risk_claims"]["pass"] = False
            hard_invariants["H1_no_fabricated_high_risk_claims"]["details"].append(
                _issue("HIGH_RISK_UNANCHORED", "Date of Injury emitted without explicit source anchor.", [claim])
            )
    mechanism = _extract_summary_field(report_text, "Mechanism")
    if mechanism:
        anchors = _find_anchors(page_text_by_number, [re.escape(mechanism.lower())], min_anchors=1)
        claim = {"type": "mechanism", "value": mechanism, "support_anchors": [a.as_dict() for a in anchors]}
        high_risk_claims.append(claim)
        if len(anchors) < 1:
            hard_invariants["H1_no_fabricated_high_risk_claims"]["pass"] = False
            hard_invariants["H1_no_fabricated_high_risk_claims"]["details"].append(
                _issue("HIGH_RISK_UNANCHORED", "Mechanism emitted without explicit source anchor.", [claim])
            )
    injuries = _extract_summary_field(report_text, "Primary Injuries")
    if injuries:
        terms = [t.strip().lower() for t in injuries.split(",") if t.strip()]
        anchors = []
        for term in terms[:3]:
            anchors.extend(_find_anchors(page_text_by_number, [re.escape(term)], min_anchors=1))
        dedup = {(a.page_number, a.snippet_hash): a for a in anchors}
        claim = {"type": "primary_injuries", "value": injuries, "support_anchors": [a.as_dict() for a in dedup.values()]}
        high_risk_claims.append(claim)
        required_injury_anchors = 1 if len(terms) <= 1 else 2
        if len(claim["support_anchors"]) < required_injury_anchors:
            hard_invariants["H1_no_fabricated_high_risk_claims"]["pass"] = False
            hard_invariants["H1_no_fabricated_high_risk_claims"]["details"].append(
                _issue(
                    "HIGH_RISK_UNANCHORED",
                    f"Primary injuries emitted without >={required_injury_anchors} explicit anchors.",
                    [claim],
                )
            )

    # H4
    timeline_rows = len(projection_entries)
    cited_rows = sum(1 for e in projection_entries if (getattr(e, "citation_display", "") or "").strip())
    timeline_citation_coverage = (cited_rows / timeline_rows) if timeline_rows else 1.0
    if timeline_rows and timeline_citation_coverage < MIN_TIMELINE_CITATION_COVERAGE:
        hard_invariants["H4_citations_present_on_timeline_rows"]["pass"] = False
        hard_invariants["H4_citations_present_on_timeline_rows"]["details"].append(
            _issue("CITATION_MISSING", f"Timeline citation coverage below threshold: {timeline_citation_coverage:.3f}")
        )

    # H5
    timestamp_mismatches = 0
    for entry in projection_entries:
        m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", getattr(entry, "date_display", "") or "")
        if not m:
            continue
        row_ord = datetime.fromisoformat(m.group(1)).date().toordinal()
        facts_blob = " ".join(getattr(entry, "facts", [])).lower()
        for ts_match in ISO_TS_RE.findall(facts_blob):
            ts_ord = datetime.fromisoformat(ts_match).date().toordinal()
            if abs(ts_ord - row_ord) > 1:
                timestamp_mismatches += 1
    if timestamp_mismatches > 0:
        hard_invariants["H5_temporal_sanity"]["pass"] = False
        hard_invariants["H5_temporal_sanity"]["details"].append(
            _issue("TEMPORAL_OUT_OF_RANGE", f"Embedded timestamp mismatches detected: {timestamp_mismatches}")
        )

    # H8
    enforce_contract = bool(ctx.get("enforce_contract_artifacts", False))
    artifact_dir = Path("data") / "artifacts" / run_id
    manifest = dict(ctx.get("artifact_manifest") or {})
    artifact_paths = {
        "chronology_pdf": str((chronology_pdf_path or (artifact_dir / "chronology.pdf")).resolve()) if (chronology_pdf_path or (artifact_dir / "chronology.pdf")) else None,
        "events_json": manifest.get("evidence_graph.json") or str((artifact_dir / "evidence_graph.json").resolve()),
        "patients_json": manifest.get("patient_partitions.json") or str((artifact_dir / "patient_partitions.json").resolve()),
        "missing_records_report_json": manifest.get("missing_records.json") or str((artifact_dir / "missing_records.json").resolve()),
        "selection_debug_json": manifest.get("selection_debug.json") or str((artifact_dir / "selection_debug.json").resolve()),
        "claim_guard_report_json": manifest.get("claim_guard_report.json") or str((artifact_dir / "claim_guard_report.json").resolve()),
        "semqa_debug_json": manifest.get("semqa_debug.json"),
    }
    artifact_warnings: list[str] = []
    missing_artifacts = []
    if chronology_pdf_path is not None and not chronology_pdf_path.exists():
        missing_artifacts.append("chronology.pdf")
    if chronology_json_path is not None and not chronology_json_path.exists():
        missing_artifacts.append("chronology.json")
    for key, p in artifact_paths.items():
        if p is None:
            artifact_warnings.append(f"missing artifact: {key} (disabled or not persisted)")
            continue
        if not Path(p).exists():
            missing_artifacts.append(Path(p).name)
            artifact_paths[key] = None
            artifact_warnings.append(f"missing artifact: {Path(p).name} (disabled or not persisted)")
    if missing_artifacts and enforce_contract:
        hard_invariants["H8_output_contract"]["pass"] = False
        hard_invariants["H8_output_contract"]["details"].append(
            _issue("MISSING_ARTIFACTS", f"Missing required artifacts: {', '.join(sorted(set(missing_artifacts)))}")
        )

    # Q1
    vitals_or_q_count = 0
    admin_count = 0
    routine_lab_rows = 0
    for entry in projection_entries:
        facts_blob = " ".join(getattr(entry, "facts", [])).lower()
        if any(m in facts_blob for m in VITALS_MARKERS) or any(m in facts_blob for m in QUESTIONNAIRE_MARKERS):
            vitals_or_q_count += 1
        if any(m in facts_blob for m in ADMIN_MARKERS):
            admin_count += 1
        if "lab" in (getattr(entry, "event_type_display", "") or "").lower() and "labs found" in facts_blob and not ABNORMAL_LAB_RE.search(facts_blob):
            routine_lab_rows += 1
    vitals_ratio = (vitals_or_q_count / timeline_rows) if timeline_rows else 0.0
    admin_ratio = (admin_count / timeline_rows) if timeline_rows else 0.0
    quality_gates["Q1_substance_ratio"]["metrics"] = {
        "vitals_pro_ratio": round(vitals_ratio, 3),
        "admin_ratio": round(admin_ratio, 3),
        "routine_labs_in_timeline": routine_lab_rows,
    }
    if vitals_ratio > MAX_VITALS_PRO_RATIO:
        quality_gates["Q1_substance_ratio"]["pass"] = False
        quality_gates["Q1_substance_ratio"]["details"].append(_issue("VITALS_PRO_RATIO_HIGH", f"Vitals/PRO ratio too high: {vitals_ratio:.3f}"))
    if admin_ratio > MAX_ADMIN_RATIO:
        quality_gates["Q1_substance_ratio"]["pass"] = False
        quality_gates["Q1_substance_ratio"]["details"].append(_issue("VITALS_PRO_RATIO_HIGH", f"Admin ratio too high: {admin_ratio:.3f}"))
    if routine_lab_rows > 0:
        quality_gates["Q1_substance_ratio"]["pass"] = False
        quality_gates["Q1_substance_ratio"]["details"].append(_issue("ROUTINE_LABS_IN_TIMELINE", f"Routine lab rows present: {routine_lab_rows}"))

    # Q2 (emergent selection sanity; no absolute row-count target)
    def _entry_substantive(e) -> bool:
        facts = " ".join(getattr(e, "facts", [])).lower()
        if not (getattr(e, "citation_display", "") or "").strip():
            return False
        return bool(
            re.search(
                r"\b(diagnosis|impression|assessment|plan|fracture|tear|radiculopathy|stenosis|infection|depo-?medrol|lidocaine|fluoroscopy|rom|range of motion|strength|work restriction|return to work|pain\s*\d|mg\b|mcg\b|ml\b|chief complaint|hpi|history of present illness|emergency visit|blood pressure|bp\s*\d{2,3}\s*/\s*\d{2,3}|heart rate|hr\s*\d+)\b",
                facts,
            )
        )

    substantive_events = sum(1 for e in projection_entries if _entry_substantive(e))
    substantive_unit_ids = {
        str(getattr(e, "event_id", "")).split("::", 1)[0]
        for e in projection_entries
        if _entry_substantive(e)
    }
    substantive_event_units = len(substantive_unit_ids)
    dated_rows = []
    for e in projection_entries:
        m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", getattr(e, "date_display", "") or "")
        if not m:
            continue
        try:
            dated_rows.append(datetime.fromisoformat(m.group(1)).date())
        except Exception:
            continue
    care_window_days = max(1, (max(dated_rows) - min(dated_rows)).days + 1) if dated_rows else 1
    event_density = substantive_events / max(care_window_days, 1)
    progression_blocks = sum(
        1
        for e in projection_entries
        if "therapy" in (getattr(e, "event_type_display", "") or "").lower()
        and re.search(r"\b(progress|re-?eval|discharge|weekly|rom|strength|pain)\b", " ".join(getattr(e, "facts", [])).lower())
    )
    stop_reason = "unknown"
    selection_debug_path = artifact_paths.get("selection_debug_json")
    if selection_debug_path and Path(selection_debug_path).exists():
        try:
            selection_debug_obj = json.loads(Path(selection_debug_path).read_text(encoding="utf-8"))
            stop_reason = str(selection_debug_obj.get("stopping_reason") or "unknown")
        except Exception:
            stop_reason = "unknown"
    emergent_selection_pass = stop_reason in {"saturation", "marginal_utility_non_positive", "safety_fuse", "no_candidates"}
    quality_gates["Q2_coverage_floor"]["metrics"] = {
        "timeline_rows": timeline_rows,
        "substantive_events": substantive_events,
        "substantive_event_units": substantive_event_units,
        "care_window_days": care_window_days,
        "event_density": round(event_density, 4),
        "progression_blocks": progression_blocks,
        "selection_stopping_reason": stop_reason,
    }
    quality_gates["Q2_coverage_floor"]["pass"] = bool(emergent_selection_pass)
    if not emergent_selection_pass:
        quality_gates["Q2_coverage_floor"]["details"].append(_issue("EMERGENT_SELECTION_STOP_MISSING", "Selection did not terminate via emergent saturation/utility criterion."))

    # Q3
    implausible_dose_change_count = len(re.findall(r"\b(21\.7\s*mg\s*->\s*\d+|\d+\s*mg\s*->\s*21\.7)\b", lower_report))
    quality_gates["Q3_med_change_semantics_sanity"]["metrics"] = {"implausible_dose_change_count": implausible_dose_change_count}
    if implausible_dose_change_count > 0:
        quality_gates["Q3_med_change_semantics_sanity"]["pass"] = False
        quality_gates["Q3_med_change_semantics_sanity"]["details"].append(
            _issue("MED_DOSE_IMPLAUSIBLE", "Implausible dose change emitted with low parse reliability.")
        )

    # Q4
    gaps_total = len(missing.get("gaps", []))
    has_gap_anchor_section = "appendix c1: gap boundary anchors" in lower_report
    has_anchor_lines = "last before gap:" in lower_report and "first after gap:" in lower_report
    # Treat short-gap noise as a formatting/content issue only when gaps are explicitly
    # routine continuity tags; do not penalize legitimate material gaps in this range.
    noisy_gap_hits = len(
        re.findall(
            r"[^\n]*\((5\d|6\d|7\d|8\d|9\d)\s+days\)\s*\[(?:routine_continuity_gap|routine_continuity_gap_collapsed)\][^\n]*",
            lower_report,
            re.IGNORECASE,
        )
    )
    quality_gates["Q4_gap_anchoring"]["metrics"] = {
        "gaps_total": gaps_total,
        "gaps_with_bracketing_citations": gaps_total if (has_gap_anchor_section and has_anchor_lines) else 0,
        "noisy_short_gap_rows": noisy_gap_hits,
    }
    if gaps_total > 0 and not (has_gap_anchor_section and has_anchor_lines):
        quality_gates["Q4_gap_anchoring"]["pass"] = False
        quality_gates["Q4_gap_anchoring"]["details"].append(_issue("GAP_UNANCHORED", "Gap boundary anchors missing."))
    if noisy_gap_hits > 0:
        quality_gates["Q4_gap_anchoring"]["pass"] = False
        quality_gates["Q4_gap_anchoring"]["details"].append(_issue("GAP_TOO_NOISY", f"Short/noisy gaps present: {noisy_gap_hits}"))
    # Repeated interval spam detector (>=3 consecutive approx-equal durations) unless explicitly collapsed.
    routine_gap_lines = re.findall(r"[^\n]*\(\d+\s+days\)\s*\[(?:routine_continuity_gap|routine_continuity_gap_collapsed)\][^\n]*", lower_report)
    gap_duration_vals = []
    for line in routine_gap_lines:
        m = re.search(r"\((\d+)\s+days\)", line)
        if m:
            gap_duration_vals.append(int(m.group(1)))
    repeated_interval_spam = 0
    streak = 1
    for i in range(1, len(gap_duration_vals)):
        if abs(gap_duration_vals[i] - gap_duration_vals[i - 1]) <= 3:
            streak += 1
            if streak >= 3:
                repeated_interval_spam += 1
        else:
            streak = 1
    if repeated_interval_spam > 0 and "routine_continuity_gap_collapsed" not in lower_report:
        quality_gates["Q4_gap_anchoring"]["pass"] = False
        quality_gates["Q4_gap_anchoring"]["details"].append(_issue("GAP_REPEATED_INTERVAL_SPAM", f"Repeated interval gaps not collapsed: {repeated_interval_spam}"))

    # Q5
    dx_contam = bool(DX_APPENDIX_CONTAM_RE.search(report_text or ""))
    quality_gates["Q5_dx_problem_purity"]["metrics"] = {"non_dx_items_in_dx_appendix": 1 if dx_contam else 0}
    if dx_contam:
        quality_gates["Q5_dx_problem_purity"]["pass"] = False
        quality_gates["Q5_dx_problem_purity"]["details"].append(_issue("DX_APPENDIX_POLLUTED", "Encounter/procedure labels found in Appendix B."))

    # Q6
    pro_signal_present = any(PRO_RE.search(" ".join(getattr(e, "facts", [])).lower()) for e in projection_entries)
    appendix_d_none = "no patient-reported outcome measures identified" in lower_report
    pro_questionnaire_events = sum(1 for e in projection_entries if PRO_RE.search(" ".join(getattr(e, "facts", [])).lower()))
    quality_gates["Q6_pro_detection_consistency"]["metrics"] = {
        "pro_questionnaire_events": pro_questionnaire_events,
        "appendix_d_present": "appendix d: patient-reported outcomes" in lower_report,
    }
    if pro_signal_present and appendix_d_none:
        quality_gates["Q6_pro_detection_consistency"]["pass"] = False
        quality_gates["Q6_pro_detection_consistency"]["details"].append(_issue("PRO_APPENDIX_CONTRADICTION", "PRO signals exist but Appendix D says none."))

    # Q7
    # Detect SDOH leak in rendered timeline text, not raw projection facts.
    sdoh_leak_events = len(
        re.findall(
            r"what happened:[^\n]*(afraid of your partner|housing|refugee|employment status|education|address|medicaid|preferred language)",
            lower_report,
        )
    )
    quality_gates["Q7_sdoh_quarantine_no_leak"]["metrics"] = {"sdoh_leak_events": sdoh_leak_events}
    if sdoh_leak_events > 0:
        quality_gates["Q7_sdoh_quarantine_no_leak"]["pass"] = False
        quality_gates["Q7_sdoh_quarantine_no_leak"]["details"].append(_issue("SDOH_LEAK_IN_TIMELINE", f"SDOH leaks: {sdoh_leak_events}"))

    # Q8
    has_top10 = "top 10 case-driving events" in lower_report
    has_issue_flags = "appendix e: issue flags" in lower_report
    top10_buckets = [
        "hospice",
        "snf",
        "death",
        "procedure",
        "emergency",
        "admission",
        "discharge",
        "imaging",
        "medication regimen change",
        "treatment gap",
    ]
    top10_diversity = sum(1 for token in top10_buckets if token in lower_report)
    quality_gates["Q8_attorney_usability_sections"]["metrics"] = {
        "top_10_section_present": has_top10,
        "issue_flags_section_present": has_issue_flags,
        "top10_bucket_diversity": top10_diversity,
    }
    if not (has_top10 and has_issue_flags):
        quality_gates["Q8_attorney_usability_sections"]["pass"] = False
        quality_gates["Q8_attorney_usability_sections"]["details"].append(
            _issue("ATTORNEY_USABILITY_MISSING", "Top 10 and/or Issue Flags section missing.")
        )
    if top10_diversity < 3:
        quality_gates["Q8_attorney_usability_sections"]["pass"] = False
        quality_gates["Q8_attorney_usability_sections"]["details"].append(
            _issue("TOP10_NOT_DIVERSE", f"Top 10 diversity below threshold: {top10_diversity}")
        )
    top10_start = lower_report.find("top 10 case-driving events")
    top10_end = lower_report.find("appendix a: medications", top10_start + 1) if top10_start >= 0 else -1
    top10_slice = lower_report[top10_start:top10_end] if (top10_start >= 0 and top10_end > top10_start) else ""
    if "routine_continuity_gap" in top10_slice or "routine_continuity_gap_collapsed" in top10_slice:
        quality_gates["Q8_attorney_usability_sections"]["pass"] = False
        quality_gates["Q8_attorney_usability_sections"]["details"].append(_issue("TOP10_CONTAINS_ROUTINE_GAP", "Top 10 contains routine continuity gap item."))
    if re.search(r"\b(acetaminophen|ibuprofen|naproxen|lisinopril|metformin|sertraline|fluoxetine)\b", top10_slice):
        quality_gates["Q8_attorney_usability_sections"]["pass"] = False
        quality_gates["Q8_attorney_usability_sections"]["details"].append(_issue("TOP10_CONTAINS_NONOPIOID_MED_CHANGE", "Top 10 contains non-opioid medication change item."))
    if "citation(s): not available" in top10_slice:
        quality_gates["Q8_attorney_usability_sections"]["pass"] = False
        quality_gates["Q8_attorney_usability_sections"]["details"].append(_issue("TOP10_ITEM_MISSING_CITATION", "Top 10 includes item lacking inline citation."))
    if "unknownwhat happened" in lower_report:
        quality_gates["Q8_attorney_usability_sections"]["pass"] = False
        quality_gates["Q8_attorney_usability_sections"]["details"].append(_issue("UNKNOWNWHAT_SEAM", "Facility/Clinician and What Happened delimiter seam detected."))
    dot_pdf_in_citations = any(
        re.search(r"\.\s+pdf\b", (getattr(e, "citation_display", "") or ""), re.IGNORECASE)
        for e in projection_entries
    )
    if dot_pdf_in_citations:
        quality_gates["Q8_attorney_usability_sections"]["pass"] = False
        quality_gates["Q8_attorney_usability_sections"]["details"].append(_issue("DOT_PDF_SPACING", "Citation filename contains dot-pdf spacing artifact."))
    top10_lines = [ln.strip() for ln in top10_slice.splitlines() if re.match(r"^\s*(?:\u2022|-)\s+", ln)]
    top10_blocks: list[str] = []
    cur_block: list[str] = []
    for raw_ln in top10_slice.splitlines():
        ln = raw_ln.strip()
        if not ln:
            continue
        if re.match(r"^\s*(?:\u2022|-)\s+", ln):
            if cur_block:
                top10_blocks.append(" ".join(cur_block))
            cur_block = [ln]
        elif cur_block:
            cur_block.append(ln)
    if cur_block:
        top10_blocks.append(" ".join(cur_block))
    top10_seen_keys: set[tuple[str, str, str]] = set()
    top10_dup_count = 0
    top10_missing_citation_rows = 0
    for ln in top10_lines:
        low_ln = ln.lower()
        # Defer citation presence check to block-level to avoid false misses on wrapped PDF lines.
        patient_match = re.search(r"gap of \d+ days \(([^)]+)\)", low_ln)
        cite_match = re.search(r"citation\(s\)\s*:\s*([^\|]+)$", low_ln)
        cite_key = (cite_match.group(1).strip() if cite_match else "")
        if "treatment gap" in low_ln:
            patient_match_2 = re.search(r"treatment gap \| ([^|]+) gap of", low_ln)
            patient = (patient_match_2.group(1).strip() if patient_match_2 else "unknown")
            tag = patient_match.group(1).strip() if patient_match else ""
            key = (patient, "material_gap", f"{tag}|{cite_key}")
        else:
            date_match = re.search(r"(?:\u2022|-)\s*([0-9]{4}-[0-9]{2}-[0-9]{2})", low_ln)
            dkey = date_match.group(1) if date_match else ""
            label_match = re.search(r"\|\s*([^|]+)\s*\|", low_ln)
            label = label_match.group(1).strip() if label_match else ""
            key = (dkey, "event", f"{label}|{cite_key}")
        if key in top10_seen_keys:
            top10_dup_count += 1
        else:
            top10_seen_keys.add(key)
    if top10_dup_count > 1:
        quality_gates["Q8_attorney_usability_sections"]["pass"] = False
        quality_gates["Q8_attorney_usability_sections"]["details"].append(_issue("TOP10_DUPLICATE_ITEM", f"Top 10 contains duplicate keyed items: {top10_dup_count}"))
    for blk in top10_blocks:
        if "citation(s):" not in blk.lower():
            top10_missing_citation_rows += 1
    if top10_missing_citation_rows > 0:
        quality_gates["Q8_attorney_usability_sections"]["pass"] = False
        quality_gates["Q8_attorney_usability_sections"]["details"].append(
            _issue("TOP10_ITEM_MISSING_CITATION", f"Top 10 rows missing inline citation token: {top10_missing_citation_rows}")
        )
    appendix_a_start = lower_report.find("appendix a: medications")
    appendix_b_start = lower_report.find("appendix b:", appendix_a_start + 1) if appendix_a_start >= 0 else -1
    appendix_a_slice = lower_report[appendix_a_start:appendix_b_start] if (appendix_a_start >= 0 and appendix_b_start > appendix_a_start) else ""
    med_seen: set[tuple[str, str]] = set()
    med_dup = 0
    for ln in appendix_a_slice.splitlines():
        m = re.search(r"(?:\u2022|-)\s*(\d{4}-\d{2}-\d{2})\s*:\s*(?:started|stopped)\s+([a-z0-9/_-]+)|(?:\u2022|-)\s*(\d{4}-\d{2}-\d{2})\s*:\s*([a-z0-9/_-]+)", ln.strip())
        if not m:
            continue
        if m.group(1) and m.group(2):
            key = (m.group(1), m.group(2))
        else:
            key = (m.group(3), m.group(4))
        if key in med_seen:
            med_dup += 1
        else:
            med_seen.add(key)
    if med_dup > 0:
        quality_gates["Q8_attorney_usability_sections"]["pass"] = False
        quality_gates["Q8_attorney_usability_sections"]["details"].append(_issue("MED_SAME_DAY_DUPLICATE", f"Same-day duplicate med lines detected: {med_dup}"))
    if re.search(r"(:\.|:\.\.|\b(?:about|of|to)\s+[a-z]\.$)", lower_report, re.MULTILINE):
        quality_gates["Q8_attorney_usability_sections"]["pass"] = False
        quality_gates["Q8_attorney_usability_sections"]["details"].append(_issue("PRO_SDOH_TRUNCATION_ARTIFACT", "Dangling punctuation or truncated fragment pattern detected."))
    if ".." in lower_report or "  " in lower_report:
        quality_gates["Q8_attorney_usability_sections"]["pass"] = False
        quality_gates["Q8_attorney_usability_sections"]["details"].append(_issue("FORMAT_SANITIZER_DEFECT", "Double punctuation or spacing artifacts detected."))
    inpatient_phrase = "inpatient course documented; ongoing monitoring and management"
    patient_sections = re.split(r"(?im)^\s*patient:\s+", report_text or "")
    inpatient_repeat_hits = 0
    for sec in patient_sections:
        c = sec.lower().count(inpatient_phrase)
        if c > 2:
            inpatient_repeat_hits += (c - 2)
    if inpatient_repeat_hits > 0:
        quality_gates["Q8_attorney_usability_sections"]["details"].append(
            _issue("INPATIENT_PROGRESS_PHRASE_REPEAT", f"Inpatient phrase repeated too often in patient sections: {inpatient_repeat_hits}")
        )

    # Final render consistency gate (cross-section + formatting coherence).
    total_surgeries_match = re.search(r"(?im)^\s*total surgeries\s*:\s*(\d+)\s*$", report_text or "")
    total_surgeries = int(total_surgeries_match.group(1)) if total_surgeries_match else None
    timeline_proc_rows = len(re.findall(r"(?im)^\s*\d{4}-\d{2}-\d{2}\s+\|\s+encounter:\s*procedure/surgery\b", report_text or ""))
    summary_no_surgery = "no surgeries documented." in lower_report
    dot_pdf_render_hits = len(re.findall(r"\b[a-z0-9_-]+\.\s+pdf\b", lower_report))
    pt_dup_fragment_hits = len(
        re.findall(
            r'pt summary:\s*"[^"]*pt evaluation/progression[^"]*;\s*pt evaluation/progression[^"]*"',
            lower_report,
            re.IGNORECASE,
        )
    )
    top10_start_r = lower_report.find("top 10 case-driving events")
    top10_end_r = lower_report.find("appendix a:", top10_start_r + 1) if top10_start_r >= 0 else -1
    top10_slice_r = lower_report[top10_start_r:top10_end_r] if (top10_start_r >= 0 and top10_end_r > top10_start_r) else ""
    top10_item_count = len(re.findall(r"(?im)^\s*(?:\u2022|-)\s+", top10_slice_r))
    timeline_bucket_count = len(
        set(
            m.group(1).strip().lower()
            for m in re.finditer(r"(?im)^\s*\d{4}-\d{2}-\d{2}\s+\|\s+encounter:\s*([^\n]+)$", report_text or "")
        )
    )
    quality_gates["Q_FINAL_RENDER_CONSISTENCY"]["metrics"] = {
        "total_surgeries": total_surgeries,
        "timeline_procedure_rows": timeline_proc_rows,
        "summary_no_surgery": summary_no_surgery,
        "dot_pdf_render_hits": dot_pdf_render_hits,
        "pt_duplicate_fragment_hits": pt_dup_fragment_hits,
        "top10_item_count": top10_item_count,
        "timeline_bucket_count": timeline_bucket_count,
    }
    if (
        total_surgeries is not None
        and total_surgeries == 0
        and timeline_proc_rows > 0
        and summary_no_surgery
    ):
        quality_gates["Q_FINAL_RENDER_CONSISTENCY"]["pass"] = False
        quality_gates["Q_FINAL_RENDER_CONSISTENCY"]["details"].append(
            _issue("SUMMARY_TIMELINE_PROCEDURE_MISMATCH", "Summary states no surgeries while timeline contains Procedure/Surgery rows.")
        )
    if dot_pdf_render_hits > 0:
        quality_gates["Q_FINAL_RENDER_CONSISTENCY"]["pass"] = False
        quality_gates["Q_FINAL_RENDER_CONSISTENCY"]["details"].append(
            _issue("DOT_PDF_SPACING_RENDERED", f"Rendered citation spacing defect dot-pdf detected ({dot_pdf_render_hits} hits).")
        )
    if pt_dup_fragment_hits > 0:
        quality_gates["Q_FINAL_RENDER_CONSISTENCY"]["pass"] = False
        quality_gates["Q_FINAL_RENDER_CONSISTENCY"]["details"].append(
            _issue("PT_ROW_DUPLICATE_FRAGMENT", f"PT summary row contains duplicated semicolon fragments ({pt_dup_fragment_hits} hits).")
        )
    if timeline_rows >= 6 and timeline_bucket_count >= 4 and top10_item_count < 2:
        quality_gates["Q_FINAL_RENDER_CONSISTENCY"]["pass"] = False
        quality_gates["Q_FINAL_RENDER_CONSISTENCY"]["details"].append(
            _issue("TOP10_TOO_THIN", f"Top 10 section too thin for available timeline diversity: {top10_item_count} items.")
        )

    # Semantic QA gates
    inpatient_rows = len(re.findall(r"\|\s*encounter:\s*inpatient progress\b", lower_report))
    inpatient_ratio = (inpatient_rows / timeline_rows) if timeline_rows else 0.0
    inpatient_source_markers = 0
    for txt in page_text_by_number.values():
        if INPATIENT_MARKER_RE.search((txt or "").lower()):
            inpatient_source_markers += 1
    outpatient_packet = inpatient_source_markers == 0
    quality_gates["Q_SEM_1_encounter_type_sanity"]["metrics"] = {
        "inpatient_rows": inpatient_rows,
        "timeline_rows": timeline_rows,
        "inpatient_ratio": round(inpatient_ratio, 3),
        "outpatient_packet": outpatient_packet,
    }
    if outpatient_packet and inpatient_ratio > 0.05:
        quality_gates["Q_SEM_1_encounter_type_sanity"]["pass"] = False
        quality_gates["Q_SEM_1_encounter_type_sanity"]["details"].append(
            _issue("SEM_INPATIENT_OVERLABEL", f"Inpatient Progress ratio too high for outpatient packet: {inpatient_ratio:.3f}")
        )

    mechanism_hits = 0
    ed_hits = 0
    for txt in page_text_by_number.values():
        low = (txt or "").lower()
        if "emergency" in low:
            ed_hits += 1
        if MECHANISM_RE.search(low):
            mechanism_hits += 1
    doi_text = _extract_summary_field(report_text, "Date of Injury")
    mechanism_text = _extract_summary_field(report_text, "Mechanism")
    incident_citation_present = "incident citation(s):" in lower_report
    quality_gates["Q_SEM_2_mechanism_required_when_present"]["metrics"] = {
        "ed_hits": ed_hits,
        "mechanism_keyword_hits": mechanism_hits,
        "doi_present": bool(doi_text),
        "mechanism_present": bool(mechanism_text),
        "incident_citation_present": incident_citation_present,
    }
    if ed_hits > 0 and mechanism_hits > 0 and not (doi_text and mechanism_text and incident_citation_present):
        quality_gates["Q_SEM_2_mechanism_required_when_present"]["pass"] = False
        quality_gates["Q_SEM_2_mechanism_required_when_present"]["details"].append(
            _issue("SEM_MISSING_DOI_MECHANISM", "Mechanism keywords present in ED context but DOI/mechanism summary not populated with citation line.")
        )

    source_proc_hits = 0
    for txt in page_text_by_number.values():
        low = (txt or "").lower()
        if len(set(PROCEDURE_ANCHOR_RE.findall(low))) >= 2:
            source_proc_hits += 1
    report_proc_anchor_hits = len(set(PROCEDURE_ANCHOR_RE.findall(lower_report)))
    pro_events = sum(1 for e in projection_entries if "procedure" in (getattr(e, "event_type_display", "") or "").lower())
    procedure_line_has_citation = any(
        (
            "procedure" in (getattr(e, "event_type_display", "") or "").lower()
            or re.search(r"\b(epidural|esi|depo-?medrol|lidocaine|fluoroscopy)\b", " ".join(getattr(e, "facts", [])).lower())
        )
        and bool((getattr(e, "citation_display", "") or "").strip())
        for e in projection_entries
    )
    quality_gates["Q_SEM_3_procedure_specificity_when_anchors_present"]["metrics"] = {
        "source_procedure_anchor_clusters": source_proc_hits,
        "pro_events": pro_events,
        "report_procedure_anchor_hits": report_proc_anchor_hits,
        "procedure_line_has_citation": procedure_line_has_citation,
    }
    if source_proc_hits > 0 and (pro_events == 0 or report_proc_anchor_hits < 1 or not procedure_line_has_citation):
        quality_gates["Q_SEM_3_procedure_specificity_when_anchors_present"]["pass"] = False
        quality_gates["Q_SEM_3_procedure_specificity_when_anchors_present"]["details"].append(
            _issue("SEM_PROCEDURE_NOT_SPECIFIC", "Procedure anchors present in source but rendered procedure lacks specific anchored details.")
        )

    appendix_b_start = lower_report.find("appendix b: diagnoses/problems")
    appendix_d_start = lower_report.find("appendix d:", appendix_b_start + 1) if appendix_b_start >= 0 else -1
    dx_slice = lower_report[appendix_b_start:appendix_d_start] if (appendix_b_start >= 0 and appendix_d_start > appendix_b_start) else ""
    dx_lines = [ln.strip(" •") for ln in dx_slice.splitlines() if ln.strip().startswith("•")]
    med_token_re = re.compile(r"\b(fracture|radiculopathy|protrusion|herniation|stenosis|infection|tear|sprain|strain|diagnosis|impression|assessment|pain|neuropathy|spondylosis|wound|icd)\b")
    medical_like = 0
    gibberish = 0
    for ln in dx_lines:
        if DX_GIBBERISH_RE.search(ln):
            gibberish += 1
        if med_token_re.search(ln) or re.search(r"\b[A-TV-Z][0-9][0-9A-Z](?:\.[0-9A-Z]{1,4})?\b", ln, re.IGNORECASE):
            medical_like += 1
    purity = (medical_like / len(dx_lines)) if dx_lines else 1.0
    quality_gates["Q_SEM_4_dx_purity"]["metrics"] = {
        "dx_lines": len(dx_lines),
        "medical_like_ratio": round(purity, 3),
        "gibberish_lines": gibberish,
    }
    if purity < 0.70 or gibberish > 0:
        quality_gates["Q_SEM_4_dx_purity"]["pass"] = False
        quality_gates["Q_SEM_4_dx_purity"]["details"].append(
            _issue("SEM_DX_PURITY_FAIL", f"Diagnosis appendix purity below threshold ({purity:.3f}) or gibberish detected ({gibberish}).")
        )

    dated_event_dates: list[datetime.date] = []
    max_event_date = None
    for entry in projection_entries:
        m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", getattr(entry, "date_display", "") or "")
        if not m:
            continue
        try:
            d = datetime.fromisoformat(m.group(1)).date()
        except Exception:
            continue
        if d.year <= 1900:
            continue
        facts_blob = " ".join(getattr(entry, "facts", [])).lower()
        if facts_blob and re.search(r"\b(product main couple design|difficult mission late kind|lorem ipsum)\b", facts_blob):
            continue
        if not _entry_substantive(entry):
            continue
        dated_event_dates.append(d)
        if max_event_date is None or d > max_event_date:
            max_event_date = d
    if len(dated_event_dates) >= 3:
        dated_event_dates = sorted(dated_event_dates)
        last = dated_event_dates[-1]
        prev = dated_event_dates[-2]
        # Robustness: a single far-future outlier date should not fail drift checks.
        if (last - prev).days > 21:
            max_event_date = prev
    care_window_end = None
    try:
        cwe = ((missing or {}).get("ruleset") or {}).get("care_window_end")
        if cwe:
            care_window_end = datetime.fromisoformat(cwe).date()
    except Exception:
        care_window_end = None
    drift_days = None
    if care_window_end and max_event_date:
        drift_days = (max_event_date - care_window_end).days
    quality_gates["Q_SEM_5_date_drift"]["metrics"] = {
        "max_event_date": max_event_date.isoformat() if max_event_date else None,
        "care_window_end": care_window_end.isoformat() if care_window_end else None,
        "drift_days": drift_days,
    }
    if drift_days is not None and drift_days > 7:
        quality_gates["Q_SEM_5_date_drift"]["pass"] = False
        quality_gates["Q_SEM_5_date_drift"]["details"].append(
            _issue("SEM_DATE_DRIFT", f"Care window end drifts beyond max dated source event by {drift_days} days.")
        )

    # Usability gates
    def _bucket(entry) -> str:
        et = (getattr(entry, "event_type_display", "") or "").lower()
        prov = (getattr(entry, "provider_display", "") or "").lower()
        facts = " ".join(getattr(entry, "facts", [])).lower()
        if "procedure" in et or "surgery" in et:
            return "procedure"
        if re.search(r"\b(depo-?medrol|lidocaine|fluoroscopy|interlaminar|transforaminal|epidural|esi|injection)\b", facts):
            return "procedure"
        if "ortho" in et or "orthopedic" in et or "ortho" in prov or "orthopedic" in prov:
            return "ortho"
        if "emergency" in et or "er visit" in et:
            return "ed"
        if "imaging" in et and "mri" in facts:
            return "mri"
        if "therapy" in et and re.search(r"\b(eval|evaluation)\b", facts):
            return "pt_eval"
        if re.search(r"\b(ortho|orthopedic)\b", facts):
            return "ortho"
        return ""

    bucket_counts = defaultdict(int)
    for e in projection_entries:
        b = _bucket(e)
        if b:
            bucket_counts[b] += 1
    timeline_start = lower_report.find("chronological medical timeline")
    timeline_end = lower_report.find("top 10 case-driving events", timeline_start + 1) if timeline_start >= 0 else -1
    timeline_slice = lower_report[timeline_start:timeline_end] if (timeline_start >= 0 and timeline_end > timeline_start) else lower_report
    if bucket_counts.get("procedure", 0) < 1 and (
        re.search(r"(?im)^\d{4}-\d{2}-\d{2}\s+\|\s+encounter:\s+procedure", timeline_slice)
        or re.search(r"\bprocedure:\s*\"", timeline_slice)
    ):
        bucket_counts["procedure"] = 1
    if bucket_counts.get("ortho", 0) < 1 and (
        "orthopedic consult" in lower_report or re.search(r"\b(orthopedic|orthopaedic|ortho)\b", lower_report)
    ):
        bucket_counts["ortho"] = 1
    quality_gates["Q_USE_1_required_buckets_present"]["metrics"] = dict(bucket_counts)
    page_blob = "\n".join(page_text_by_number.values()).lower()
    procedure_anchor_terms = re.findall(
        r"\b(depo-?medrol|lidocaine|fluoroscopy|interlaminar|transforaminal|epidural steroid injection|esi)\b",
        page_blob,
        flags=re.IGNORECASE,
    )
    procedure_anchor_count = len({t.lower() for t in procedure_anchor_terms})
    bucket_source_available = {
        "ed": bool(
            re.search(r"\b(emergency|ed visit|er visit)\b", page_blob)
            and re.search(r"\b(chief complaint|hpi|assessment|diagnosis|clinical impression)\b", page_blob)
        ),
        "mri": bool(
            re.search(
                r"\bmri\b.{0,160}\b(impression|finding|radiology report)\b|\b(impression|finding|radiology report)\b.{0,160}\bmri\b",
                page_blob,
                re.IGNORECASE | re.DOTALL,
            )
        ),
        "pt_eval": bool(re.search(r"\b(pt eval|physical therapy evaluation|range of motion|rom|strength)\b", page_blob)),
        "ortho": bool(re.search(r"\b(ortho|orthopedic)\b", page_blob)),
        "procedure": bool(
            re.search(r"\b(epidural steroid injection|esi)\b", page_blob)
            or procedure_anchor_count >= 2
        ),
    }
    required_buckets = [b for b, available in bucket_source_available.items() if available]
    missing_buckets = [b for b in required_buckets if bucket_counts.get(b, 0) < 1]
    if missing_buckets:
        quality_gates["Q_USE_1_required_buckets_present"]["pass"] = False
        quality_gates["Q_USE_1_required_buckets_present"]["details"].append(
            _issue("USE_REQUIRED_BUCKETS_MISSING", f"Missing required timeline buckets: {', '.join(missing_buckets)}")
        )

    substantive_rows = 0
    for e in projection_entries:
        facts = " ".join(getattr(e, "facts", [])).lower()
        et = (getattr(e, "event_type_display", "") or "").lower()
        hit = bool(
            re.search(
                r"\b(impression|assessment|diagnosis|plan|fracture|tear|radiculopathy|depo-?medrol|lidocaine|fluoroscopy|rom|range of motion|strength|work restriction|return to work|pain\s*\d|injection|procedure)\b",
                facts,
            )
        )
        if not hit and any(tok in et for tok in ("emergency", "admission", "discharge", "procedure", "imaging", "therapy")):
            hit = True
        if hit:
            substantive_rows += 1
    quality_gates["Q_USE_2_min_substantive_rows"]["metrics"] = {
        "substantive_rows": substantive_rows,
        "timeline_rows": timeline_rows,
    }
    # Scale threshold for short timelines so tiny packets are not required to reach
    # an absolute minimum row count that exceeds available rows.
    substantive_threshold = min(
        max(1, timeline_rows),
        max(6, min(12, int(round(timeline_rows * 0.6)) if timeline_rows else 6)),
    )
    quality_gates["Q_USE_2_min_substantive_rows"]["metrics"]["substantive_threshold"] = substantive_threshold
    if substantive_rows < substantive_threshold:
        quality_gates["Q_USE_2_min_substantive_rows"]["pass"] = False
        quality_gates["Q_USE_2_min_substantive_rows"]["details"].append(
            _issue("USE_SUBSTANCE_TOO_LOW", f"Substantive timeline rows below threshold: {substantive_rows}")
        )

    has_impression = bool(re.search(r"\bimpression\b", lower_report))
    quality_gates["Q_USE_3_imaging_impression_present"]["metrics"] = {"impression_present": has_impression}
    if not has_impression:
        quality_gates["Q_USE_3_imaging_impression_present"]["pass"] = False
        quality_gates["Q_USE_3_imaging_impression_present"]["details"].append(
            _issue("USE_NO_IMAGING_IMPRESSION", "No imaging impression text detected in timeline output.")
        )

    noise_terms = ["product main couple design", "difficult mission late kind"]
    noise_hits = [t for t in noise_terms if t in lower_report]
    quality_gates["Q_USE_4_no_noise_gibberish"]["metrics"] = {"noise_hits": len(noise_hits)}
    if noise_hits:
        quality_gates["Q_USE_4_no_noise_gibberish"]["pass"] = False
        quality_gates["Q_USE_4_no_noise_gibberish"]["details"].append(
            _issue("USE_NOISE_GIBBERISH", f"Noise phrases detected in output: {', '.join(noise_hits)}")
        )

    placeholder_hits = len(
        re.findall(
            r"\b(limited detail|encounter recorded|continuity of care|documentation noted)\b",
            lower_report,
        )
    )
    quality_gates["Q_USE_5_no_placeholder_language"]["metrics"] = {"placeholder_hits": placeholder_hits}
    if placeholder_hits > 0:
        quality_gates["Q_USE_5_no_placeholder_language"]["pass"] = False
        quality_gates["Q_USE_5_no_placeholder_language"]["details"].append(
            _issue("USE_PLACEHOLDER_LANGUAGE", f"Placeholder language detected in timeline output ({placeholder_hits} hits).")
        )

    # High-density ratio gate
    def _subst_score(entry) -> int:
        facts = " ".join(getattr(entry, "facts", [])).lower()
        et = (getattr(entry, "event_type_display", "") or "").lower()
        score = 0
        if re.search(r"\b(diagnosis|assessment|impression|plan|fracture|tear|radiculopathy|infection|stenosis)\b", facts):
            score += 2
        if re.search(r"\b(depo-?medrol|lidocaine|fluoroscopy|epidural|esi|procedure|surgery)\b", facts):
            score += 2
        if re.search(r"\b(rom|range of motion|strength|work restriction|return to work|mg\b|mcg\b|ml\b)\b", facts):
            score += 2
        if re.search(r"\bpain\b[^0-9]{0,10}\d{1,2}\s*(?:/10)?\b", facts):
            score += 2
        if re.search(r"\b(chief complaint|hpi|history of present illness|clinical impression|disc protrusion|radicular)\b", facts):
            score += 2
        if any(tok in et for tok in ("emergency", "admission", "discharge", "procedure", "imaging")):
            score += 2
        if "therapy" in et and re.search(r"\b(pain|rom|range of motion|strength|eval|evaluation|plan)\b", facts):
            score += 2
        return score

    # Compute high-density ratio from rendered timeline rows (lawyer-visible output), with
    # projection fallback when row parsing is unavailable.
    timeline_start = lower_report.find("chronological medical timeline")
    timeline_end = lower_report.find("top 10 case-driving events", timeline_start + 1) if timeline_start >= 0 else -1
    timeline_block = report_text[timeline_start: timeline_end if timeline_end > timeline_start else len(report_text)] if timeline_start >= 0 else report_text
    row_blobs: list[str] = []
    current: list[str] = []
    for raw_line in timeline_block.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if re.match(r"^(?:\d{4}-\d{2}-\d{2}|Undated)\s+\|\s+Encounter:\s+", line, re.IGNORECASE):
            if current:
                row_blobs.append(" ".join(current))
            current = [line]
            continue
        if current:
            current.append(line)
    if current:
        row_blobs.append(" ".join(current))

    def _subst_score_text(blob: str) -> int:
        low = (blob or "").lower()
        score = 0
        if re.search(r"\b(diagnosis|assessment|impression|plan|fracture|tear|radiculopathy|infection|stenosis)\b", low):
            score += 2
        if re.search(r"\b(depo-?medrol|lidocaine|fluoroscopy|epidural|esi|procedure|surgery)\b", low):
            score += 2
        if re.search(r"\b(rom|range of motion|strength|work restriction|return to work|mg\b|mcg\b|ml\b)\b", low):
            score += 2
        if re.search(r"\bpain\b[^0-9]{0,10}\d{1,2}\s*(?:/10)?\b", low):
            score += 2
        if re.search(r"\b(chief complaint|hpi|history of present illness|clinical impression|disc protrusion|radicular)\b", low):
            score += 2
        if re.search(r"\b(emergency|admission|discharge|procedure|imaging)\b", low):
            score += 2
        return score

    if row_blobs:
        high_rows = sum(1 for row in row_blobs if _subst_score_text(row) >= 4 and re.search(r"citation\(s\):", row, re.IGNORECASE))
        density_rows = len(row_blobs)
    else:
        high_rows = sum(1 for e in projection_entries if _subst_score(e) >= 4 and (getattr(e, "citation_display", "") or "").strip())
        density_rows = timeline_rows
    high_ratio = (high_rows / density_rows) if density_rows else 1.0
    quality_gates["Q_USE_HIGH_DENSITY_RATIO"]["metrics"] = {"high_substance_rows": high_rows, "timeline_rows": density_rows, "high_substance_ratio": round(high_ratio, 3)}
    if density_rows and high_ratio < 0.7:
        quality_gates["Q_USE_HIGH_DENSITY_RATIO"]["pass"] = False
        quality_gates["Q_USE_HIGH_DENSITY_RATIO"]["details"].append(
            _issue("USE_HIGH_DENSITY_RATIO_LOW", f"High-substance ratio below threshold: {high_ratio:.3f}")
        )

    # Flow-noise event gate
    flow_noise_rows = 0
    for e in projection_entries:
        facts = " ".join(getattr(e, "facts", [])).lower()
        ts_hits = len(re.findall(r"\b([01]?\d|2[0-3]):[0-5]\d\b", facts))
        med_hits = len(re.findall(r"\b(impression|assessment|diagnosis|fracture|tear|infection|mri|x-?ray|rom|strength|pain|medication|injection|procedure|discharge|admission)\b", facts))
        if ts_hits >= 10 and med_hits < 2:
            flow_noise_rows += 1
    quality_gates["Q_USE_NO_FLOW_NOISE_EVENTS"]["metrics"] = {"timeline_rows_from_flowsheet_noise": flow_noise_rows}
    if flow_noise_rows > 0:
        quality_gates["Q_USE_NO_FLOW_NOISE_EVENTS"]["pass"] = False
        quality_gates["Q_USE_NO_FLOW_NOISE_EVENTS"]["details"].append(
            _issue("USE_FLOW_NOISE_ROWS", f"Flow/noise rows detected in timeline: {flow_noise_rows}")
        )

    # Template-language ban gate
    template_hits = len(
        re.findall(
            r"acute-care intervention performed|clinical encounter includes extracted medical findings|documented management actions are summarized|outcome supported by cited record text",
            lower_report,
        )
    )
    quality_gates["Q_USE_NO_TEMPLATE_LANGUAGE"]["metrics"] = {"template_phrase_hits": template_hits}
    if template_hits > 0:
        quality_gates["Q_USE_NO_TEMPLATE_LANGUAGE"]["pass"] = False
        quality_gates["Q_USE_NO_TEMPLATE_LANGUAGE"]["details"].append(
            _issue("USE_TEMPLATE_LANGUAGE", f"Template language found in report: {template_hits} hits.")
        )

    # No-meta-language gate for timeline text.
    meta_hits = len(re.findall(r"\b(identified from source|markers|extracted|encounter identified|not stated in records|identified|documented)\b", timeline_slice))
    quality_gates["Q_USE_NO_META_LANGUAGE"]["metrics"] = {
        "timeline_meta_language_hits": meta_hits,
        "timeline_contains_meta_language": meta_hits > 0,
    }
    if meta_hits > 0:
        quality_gates["Q_USE_NO_META_LANGUAGE"]["pass"] = False
        quality_gates["Q_USE_NO_META_LANGUAGE"]["details"].append(
            _issue("USE_META_LANGUAGE", f"Meta-language found in timeline: {meta_hits} hits.")
        )

    # Verbatim snippet density gate
    # Measure rendered output quality directly instead of counting hidden projection facts.
    timeline_rows_rendered = len(re.findall(r"(?im)^\d{4}-\d{2}-\d{2}\s+\|\s+encounter:", timeline_slice))
    snippet_rows = len(
        re.findall(
            r'(?im)^((chief complaint|hpi|assessment|plan|impression|meds given|medications|vitals|procedure|guidance|complications)\s*:\s*\"[^\"]+\"|\"[^\"]+\")',
            timeline_slice,
        )
    )
    quoted_rows = len(
        re.findall(
            r'(?im)^.*"(?:[^"\n]{24,})".*$',
            timeline_slice,
        )
    )
    quality_gates["Q_USE_VERBATIM_SNIPPETS"]["metrics"] = {"rows_with_direct_source_snippets": quoted_rows}
    # Calibrate to rendered timeline rows (lawyer-visible output), not projection size.
    quoted_rows_threshold = min(3, max(1, timeline_rows_rendered or timeline_rows))
    quality_gates["Q_USE_VERBATIM_SNIPPETS"]["metrics"]["rows_with_direct_source_snippets_threshold"] = quoted_rows_threshold
    quality_gates["Q_USE_VERBATIM_SNIPPETS"]["metrics"]["rows_with_direct_snippet"] = snippet_rows
    if quoted_rows < quoted_rows_threshold and snippet_rows < quoted_rows_threshold:
        quality_gates["Q_USE_VERBATIM_SNIPPETS"]["pass"] = False
        quality_gates["Q_USE_VERBATIM_SNIPPETS"]["details"].append(
            _issue("USE_VERBATIM_SNIPPETS_LOW", f"Rows with verbatim snippets below threshold: {quoted_rows}")
        )

    # Direct snippet required: >=80% timeline rows with direct quoted clinical text.
    snippet_ratio = (min(snippet_rows, timeline_rows_rendered) / timeline_rows_rendered) if timeline_rows_rendered else 1.0
    quality_gates["Q_USE_DIRECT_SNIPPET_REQUIRED"]["metrics"] = {
        "timeline_rows_rendered": timeline_rows_rendered,
        "rows_with_direct_snippet": snippet_rows,
        "direct_snippet_ratio": round(snippet_ratio, 3),
    }
    if timeline_rows_rendered and snippet_ratio < 0.8:
        quality_gates["Q_USE_DIRECT_SNIPPET_REQUIRED"]["pass"] = False
        quality_gates["Q_USE_DIRECT_SNIPPET_REQUIRED"]["details"].append(
            _issue("USE_DIRECT_SNIPPET_RATIO_LOW", f"Direct clinical snippet ratio below threshold: {snippet_ratio:.3f}")
        )

    # Extraction sufficiency gate for large packets.
    pt_note_pages = sum(
        1
        for txt in page_text_by_number.values()
        if re.search(r"\b(physical therapy|pt note|pt daily|pt progress|pt discharge|pt eval)\b", (txt or "").lower())
    )
    substantive_pt_events = sum(
        1
        for e in projection_entries
        if "therapy" in (getattr(e, "event_type_display", "") or "").lower() and _entry_substantive(e)
    )
    selection_stop_reason = "unknown"
    selection_debug_path = artifact_paths.get("selection_debug_json")
    if selection_debug_path and Path(selection_debug_path).exists():
        try:
            sd_obj = json.loads(Path(selection_debug_path).read_text(encoding="utf-8"))
            selection_stop_reason = str(sd_obj.get("stopping_reason") or "unknown")
        except Exception:
            selection_stop_reason = "unknown"
    required_bucket_counts = quality_gates.get("Q_USE_1_required_buckets_present", {}).get("metrics", {}) or {}
    required_bucket_present = sum(1 for _k, v in required_bucket_counts.items() if int(v or 0) > 0)
    suff_metrics = {
        "source_pages": source_pages,
        "substantive_events": substantive_events,
        "timeline_rows": timeline_rows,
        "pt_note_pages": pt_note_pages,
        "substantive_events_from_pt": substantive_pt_events,
        "required_bucket_present_count": required_bucket_present,
        "selection_stopping_reason": selection_stop_reason,
    }
    quality_gates["Q_USE_EXTRACTION_SUFFICIENCY"]["metrics"] = suff_metrics
    if source_pages > 300:
        if selection_stop_reason not in {"saturation", "marginal_utility_non_positive", "safety_fuse", "no_candidates"}:
            quality_gates["Q_USE_EXTRACTION_SUFFICIENCY"]["pass"] = False
            quality_gates["Q_USE_EXTRACTION_SUFFICIENCY"]["details"].append(
                _issue("USE_SELECTION_STOP_INVALID", f"Emergent selector stop reason invalid: {selection_stop_reason}")
            )
        min_substantive_for_present = max(2, required_bucket_present)
        if substantive_events < min_substantive_for_present:
            quality_gates["Q_USE_EXTRACTION_SUFFICIENCY"]["pass"] = False
            quality_gates["Q_USE_EXTRACTION_SUFFICIENCY"]["details"].append(
                _issue("USE_SUBSTANTIVE_EVENTS_LOW", f"Substantive events below milestone floor: {substantive_events} < {min_substantive_for_present}")
            )
        if timeline_rows < max(4, required_bucket_present):
            quality_gates["Q_USE_EXTRACTION_SUFFICIENCY"]["pass"] = False
            quality_gates["Q_USE_EXTRACTION_SUFFICIENCY"]["details"].append(
                _issue("USE_TIMELINE_ROWS_LOW", f"Timeline rows below milestone floor: {timeline_rows}")
            )
    # For PT-heavy packets, enforce at least one strong PT milestone, and require two only
    # when packet size is very large.
    pt_min_required = 2 if pt_note_pages > 200 else 1
    if pt_note_pages > 50 and substantive_pt_events < pt_min_required:
        quality_gates["Q_USE_EXTRACTION_SUFFICIENCY"]["pass"] = False
        quality_gates["Q_USE_EXTRACTION_SUFFICIENCY"]["details"].append(
            _issue("USE_PT_SUBSTANCE_LOW", f"PT substantive events too low for PT-heavy packet: {substantive_pt_events}")
        )

    hard_pass = all(v["pass"] for v in hard_invariants.values())
    # Context-aware required quality gates.
    require_q2 = source_pages >= 300
    require_q4 = source_pages >= 300 and gaps_total > 0
    required_quality_keys = {
        "Q1_substance_ratio",
        "Q3_med_change_semantics_sanity",
        "Q5_dx_problem_purity",
        "Q6_pro_detection_consistency",
        "Q7_sdoh_quarantine_no_leak",
        "Q8_attorney_usability_sections",
        "Q_SEM_1_encounter_type_sanity",
        "Q_SEM_2_mechanism_required_when_present",
        "Q_SEM_3_procedure_specificity_when_anchors_present",
        "Q_SEM_4_dx_purity",
        "Q_SEM_5_date_drift",
        "Q_USE_1_required_buckets_present",
        "Q_USE_2_min_substantive_rows",
        "Q_USE_3_imaging_impression_present",
        "Q_USE_4_no_noise_gibberish",
        "Q_USE_5_no_placeholder_language",
        "Q_USE_HIGH_DENSITY_RATIO",
        "Q_USE_NO_FLOW_NOISE_EVENTS",
        "Q_USE_NO_TEMPLATE_LANGUAGE",
        "Q_USE_VERBATIM_SNIPPETS",
        "Q_USE_EXTRACTION_SUFFICIENCY",
        "Q_USE_NO_META_LANGUAGE",
        "Q_USE_DIRECT_SNIPPET_REQUIRED",
        "Q_FINAL_RENDER_CONSISTENCY",
    }
    if require_q2:
        required_quality_keys.add("Q2_coverage_floor")
    if require_q4:
        required_quality_keys.add("Q4_gap_anchoring")
    quality_pass = all(quality_gates[k]["pass"] for k in sorted(required_quality_keys))
    hard_failures: list[dict[str, Any]] = []
    for block in hard_invariants.values():
        hard_failures.extend(block["details"])

    rubric = 100
    rubric -= min(60, 15 * len(hard_failures))
    rubric -= int(max(0.0, vitals_ratio - MAX_VITALS_PRO_RATIO) * 100)
    rubric -= int(max(0.0, admin_ratio - MAX_ADMIN_RATIO) * 100)
    rubric -= min(20, 5 * sum(1 for q in quality_gates.values() if not q["pass"]))
    rubric = max(0, min(100, rubric))
    polish_warning_count = sum(
        1
        for d in quality_gates["Q8_attorney_usability_sections"]["details"]
        if d.get("code") in {"FORMAT_SANITIZER_DEFECT", "INPATIENT_PROGRESS_PHRASE_REPEAT"}
    )
    if hard_pass and quality_pass and polish_warning_count == 0:
        rubric += 5
    pass_run = bool(hard_pass and quality_pass and rubric >= TARGET_SCORE)

    # per-patient metrics
    per_patient: list[dict[str, Any]] = []
    by_label: dict[str, list[Any]] = defaultdict(list)
    for entry in projection_entries:
        by_label[getattr(entry, "patient_label", "Unknown Patient")].append(entry)
    for label in sorted(by_label.keys()):
        entries_for_label = by_label[label]
        rows = len(entries_for_label)
        cited = sum(1 for e in entries_for_label if (getattr(e, "citation_display", "") or "").strip())
        vq = sum(
            1
            for e in entries_for_label
            if any(m in " ".join(getattr(e, "facts", [])).lower() for m in VITALS_MARKERS + QUESTIONNAIRE_MARKERS)
        )
        per_patient.append(
            {
                "patient_scope_id": hashlib.sha1(label.encode("utf-8")).hexdigest()[:8],
                "label": label,
                "date_range": {"start": None, "end": None},
                "metrics": {
                    "timeline_rows": rows,
                    "timeline_citation_coverage": round((cited / rows), 3) if rows else 1.0,
                    "vitals_pro_ratio": round((vq / rows), 3) if rows else 0.0,
                    "routine_labs_in_timeline": sum(
                        1
                        for e in entries_for_label
                        if "lab" in (getattr(e, "event_type_display", "") or "").lower()
                        and "labs found" in " ".join(getattr(e, "facts", [])).lower()
                        and not ABNORMAL_LAB_RE.search(" ".join(getattr(e, "facts", [])).lower())
                    ),
                },
                "failures": [],
            }
        )

    checklist = {
        "run_id": run_id,
        "source_pdf": source_pdf,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "tool_version": TOOL_VERSION,
        "pass": pass_run,
        "score_0_100": rubric,
        "thresholds": {
            "target_score": TARGET_SCORE,
            "min_timeline_citation_coverage": MIN_TIMELINE_CITATION_COVERAGE,
            "max_vitals_pro_ratio": MAX_VITALS_PRO_RATIO,
            "max_admin_ratio": MAX_ADMIN_RATIO,
        },
        "hard_invariants": hard_invariants,
        "quality_gates": quality_gates,
        "hard_failures": hard_failures,
        "claims": {"high_risk": high_risk_claims},
        "metrics": {
            "timeline_rows": timeline_rows,
            "timeline_citation_coverage": round(timeline_citation_coverage, 3),
            "vitals_questionnaire_ratio": round(vitals_ratio, 3),
            "admin_ratio": round(admin_ratio, 3),
            "extracted_high_value_events": substantive_events,
            "selection_stopping_reason": stop_reason,
            "emergent_selection_pass": bool(emergent_selection_pass),
            "unknown_patient_rows": len(unknown_timeline),
            "patient_scope_violation_count": len(patient_scope_violations),
            "provider_contamination_count": len(contaminated),
            "routine_lab_rows": routine_lab_rows,
            "pro_signal_present": bool(pro_signal_present),
            "pro_events": int(pro_events),
            "timestamp_mismatch_count": int(timestamp_mismatches),
        },
        "per_patient": per_patient,
        "unassigned": {
            "pages": [],
            "events": sum(1 for e in events if (e.extensions or {}).get("patient_scope_id") in (None, "", "ps_unknown")),
            "excluded_from_gaps": True,
        },
        "artifacts": artifact_paths,
        "warnings": artifact_warnings,
        "failure_summary": {
            "hard_failed": not hard_pass,
            "quality_failed": not quality_pass,
            "contract_failed": not hard_invariants["H8_output_contract"]["pass"],
            "required_quality_gates": sorted(required_quality_keys),
        },
        "scores": {
            "rubric_score_0_100": rubric,
            "breakdown": {
                "hard_failures": len(hard_failures),
                "citation_coverage": round(timeline_citation_coverage, 3),
                "vitals_questionnaire_ratio": round(vitals_ratio, 3),
                "admin_ratio": round(admin_ratio, 3),
                "emergent_selection_pass": bool(emergent_selection_pass),
            },
        },
    }
    return checklist


def write_litigation_checklist(path: Path, checklist: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(checklist, indent=2), encoding="utf-8")
