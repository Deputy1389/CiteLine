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
TARGET_SCORE = 90
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
        anchors = _find_anchors(page_text_by_number, [re.escape(mechanism.lower())], min_anchors=2)
        claim = {"type": "mechanism", "value": mechanism, "support_anchors": [a.as_dict() for a in anchors]}
        high_risk_claims.append(claim)
        if len(anchors) < 2:
            hard_invariants["H1_no_fabricated_high_risk_claims"]["pass"] = False
            hard_invariants["H1_no_fabricated_high_risk_claims"]["details"].append(
                _issue("HIGH_RISK_UNANCHORED", "Mechanism emitted without >=2 explicit anchors.", [claim])
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
        if len(claim["support_anchors"]) < 2:
            hard_invariants["H1_no_fabricated_high_risk_claims"]["pass"] = False
            hard_invariants["H1_no_fabricated_high_risk_claims"]["details"].append(
                _issue("HIGH_RISK_UNANCHORED", "Primary injuries emitted without >=2 explicit anchors.", [claim])
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
    artifact_paths = {
        "chronology_pdf": str((artifact_dir / "chronology.pdf").resolve()),
        "events_json": str((artifact_dir / "evidence_graph.json").resolve()),
        "patients_json": str((artifact_dir / "patient_partitions.json").resolve()),
        "missing_records_report_json": str((artifact_dir / "missing_records.json").resolve()),
    }
    missing_artifacts = []
    if chronology_pdf_path is not None and not chronology_pdf_path.exists():
        missing_artifacts.append("chronology.pdf")
    if chronology_json_path is not None and not chronology_json_path.exists():
        missing_artifacts.append("chronology.json")
    for p in artifact_paths.values():
        if not Path(p).exists():
            missing_artifacts.append(Path(p).name)
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

    # Q2
    extracted_high_value = sum(1 for e in events if (e.extensions or {}).get("is_care_event") is True)
    coverage_floor = max(25, int(round(0.15 * extracted_high_value))) if extracted_high_value else 0
    if source_pages < 40:
        coverage_floor = min(coverage_floor, 6)
    coverage_floor_pass = timeline_rows >= coverage_floor if coverage_floor > 0 else True
    quality_gates["Q2_coverage_floor"]["metrics"] = {"timeline_rows": timeline_rows, "coverage_floor": coverage_floor}
    quality_gates["Q2_coverage_floor"]["pass"] = bool(coverage_floor_pass)
    if not coverage_floor_pass:
        quality_gates["Q2_coverage_floor"]["details"].append(_issue("COVERAGE_FLOOR_FAIL", "Timeline rows below coverage floor."))

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
    quality_gates["Q4_gap_anchoring"]["metrics"] = {
        "gaps_total": gaps_total,
        "gaps_with_bracketing_citations": gaps_total if (has_gap_anchor_section and has_anchor_lines) else 0,
    }
    if gaps_total > 0 and not (has_gap_anchor_section and has_anchor_lines):
        quality_gates["Q4_gap_anchoring"]["pass"] = False
        quality_gates["Q4_gap_anchoring"]["details"].append(_issue("GAP_UNANCHORED", "Gap boundary anchors missing."))

    # Q5
    dx_contam = bool(DX_APPENDIX_CONTAM_RE.search(report_text or ""))
    quality_gates["Q5_dx_problem_purity"]["metrics"] = {"non_dx_items_in_dx_appendix": 1 if dx_contam else 0}
    if dx_contam:
        quality_gates["Q5_dx_problem_purity"]["pass"] = False
        quality_gates["Q5_dx_problem_purity"]["details"].append(_issue("DX_APPENDIX_POLLUTED", "Encounter/procedure labels found in Appendix B."))

    # Q6
    pro_signal_present = any(PRO_RE.search(" ".join(getattr(e, "facts", [])).lower()) for e in projection_entries)
    appendix_d_none = "no patient-reported outcome measures identified" in lower_report
    quality_gates["Q6_pro_detection_consistency"]["metrics"] = {
        "pro_events": sum(1 for e in projection_entries if PRO_RE.search(" ".join(getattr(e, "facts", [])).lower())),
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
    quality_gates["Q8_attorney_usability_sections"]["metrics"] = {"top_10_section_present": has_top10, "issue_flags_section_present": has_issue_flags}
    if not (has_top10 and has_issue_flags):
        quality_gates["Q8_attorney_usability_sections"]["pass"] = False
        quality_gates["Q8_attorney_usability_sections"]["details"].append(
            _issue("ATTORNEY_USABILITY_MISSING", "Top 10 and/or Issue Flags section missing.")
        )

    hard_pass = all(v["pass"] for v in hard_invariants.values())
    # Context-aware required quality gates.
    require_q2 = source_pages >= 300
    require_q4 = source_pages >= 300 and gaps_total > 0
    required_quality_keys = {"Q1_substance_ratio", "Q3_med_change_semantics_sanity", "Q5_dx_problem_purity", "Q6_pro_detection_consistency", "Q7_sdoh_quarantine_no_leak", "Q8_attorney_usability_sections"}
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
    rubric = max(0, rubric)
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
            "extracted_high_value_events": extracted_high_value,
            "coverage_floor": coverage_floor,
            "coverage_floor_pass": bool(coverage_floor_pass),
            "unknown_patient_rows": len(unknown_timeline),
            "patient_scope_violation_count": len(patient_scope_violations),
            "provider_contamination_count": len(contaminated),
            "routine_lab_rows": routine_lab_rows,
            "pro_signal_present": bool(pro_signal_present),
            "timestamp_mismatch_count": int(timestamp_mismatches),
        },
        "per_patient": per_patient,
        "unassigned": {
            "pages": [],
            "events": sum(1 for e in events if (e.extensions or {}).get("patient_scope_id") in (None, "", "ps_unknown")),
            "excluded_from_gaps": True,
        },
        "artifacts": artifact_paths,
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
                "coverage_floor_pass": bool(coverage_floor_pass),
            },
        },
    }
    return checklist


def write_litigation_checklist(path: Path, checklist: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(checklist, indent=2), encoding="utf-8")
