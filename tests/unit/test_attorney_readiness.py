from __future__ import annotations

from apps.worker.lib.attorney_readiness import build_attorney_readiness_report


def _ctx(page_text=None):
    return {"page_text_by_number": page_text or {}}


def _ctx_with_projection(page_text=None, projection_entries=None):
    return {"page_text_by_number": page_text or {}, "projection_entries": projection_entries or []}


def test_attorney_readiness_fails_missing_sections():
    report = "Chronological Medical Timeline\n2025-01-01 | Encounter: ED Visit\nCitation(s): a.pdf p. 1"
    out = build_attorney_readiness_report(report, _ctx())
    assert out["attorney_ready_pass"] is False
    codes = {f["code"] for f in out["failures"]}
    assert "AR_MISSING_REQUIRED_SECTIONS" in codes


def test_attorney_readiness_fails_missing_required_buckets():
    report = """
Medical Chronology Analysis
Chronological Medical Timeline
2025-01-01 | Encounter: Therapy Visit
Facility/Clinician: PT
"Pain 6/10; Cervical ROM 30 deg; Strength 4/5."
Citation(s): packet.pdf p. 3
Top 10 Case-Driving Events
Appendix A:
Appendix B:
Appendix C
"""
    ctx = _ctx(page_text={1: "ED triage HPI after MVC. MRI impression shows C5-6 protrusion. Orthopedic assessment and plan."})
    out = build_attorney_readiness_report(report, ctx)
    assert out["attorney_ready_pass"] is False
    codes = {f["code"] for f in out["failures"]}
    assert "AR_REQUIRED_BUCKETS_MISSING" in codes


def test_attorney_readiness_passes_fact_dense_cited_rows():
    report = """
Medical Chronology Analysis
Chronological Medical Timeline
2025-01-01 | Encounter: Emergency Visit
Facility/Clinician: ED
"Chief complaint: neck pain after MVC. BP 138/88 pain 8/10. Toradol 30mg IM."
Citation(s): packet.pdf p. 1
2025-01-02 | Encounter: Imaging Study
Facility/Clinician: Radiology
"MRI cervical spine impression: C5-6 disc protrusion with mild foraminal narrowing."
Citation(s): packet.pdf p. 2
2025-01-03 | Encounter: Orthopedic Consultation
Facility/Clinician: Ortho
"Assessment: cervical radiculopathy at C6-7 with pain 7/10. Plan: continue PT and consider ESI."
Citation(s): packet.pdf p. 3
2025-01-04 | Encounter: Procedure/Surgery
Facility/Clinician: Pain Mgmt
"Procedure: epidural steroid injection at C6-7 with Depo-Medrol 80 mg and lidocaine under fluoroscopy."
Citation(s): packet.pdf p. 4
Top 10 Case-Driving Events
Appendix A:
Appendix B:
Appendix C
"""
    ctx = _ctx(page_text={1: "ED triage HPI", 2: "MRI IMPRESSION", 3: "Orthopedic assessment plan", 4: "Depo-Medrol lidocaine fluoroscopy"})
    out = build_attorney_readiness_report(report, ctx)
    assert out["attorney_ready_pass"] is True
    assert out["attorney_ready_score_0_100"] >= 90


def test_attorney_required_bucket_uses_projection_fallback_when_text_parse_is_sparse():
    from types import SimpleNamespace

    report = """
Medical Chronology Analysis
Chronological Medical Timeline
2025-01-01 | Encounter: Clinical Note
Facility/Clinician: PT
"Pain 6/10."
Citation(s): packet.pdf p. 3
Top 10 Case-Driving Events
Appendix A:
Appendix B:
Appendix C
"""
    projection_entries = [
        SimpleNamespace(
            date_display="2025-01-01 (time not documented)",
            event_type_display="Imaging Study",
            facts=["MRI cervical spine impression: C5-6 protrusion."],
            citation_display="packet.pdf p. 3",
        )
    ]
    ctx = _ctx_with_projection(
        page_text={1: "MRI impression shows C5-6 protrusion."},
        projection_entries=projection_entries,
    )
    out = build_attorney_readiness_report(report, ctx)
    codes = {f["code"] for f in out["failures"]}
    assert "AR_REQUIRED_BUCKETS_MISSING" not in codes


def test_attorney_density_counts_milestone_rows_with_single_strong_fact_category():
    report = """
Medical Chronology Analysis
Chronological Medical Timeline
2025-01-01 | Encounter: Procedure/Surgery
Facility/Clinician: Pain
Procedure: "Epidural steroid injection."
Citation(s): packet.pdf p. 7
2025-01-02 | Encounter: Emergency Visit
Facility/Clinician: ED
Chief Complaint: "Neck pain after MVC."
Citation(s): packet.pdf p. 8
Top 10 Case-Driving Events
Appendix A:
Appendix B:
Appendix C
"""
    ctx = _ctx(page_text={1: "ED triage", 2: "Epidural steroid injection"})
    out = build_attorney_readiness_report(report, ctx)
    codes = {f["code"] for f in out["failures"]}
    assert "AR_FACT_DENSITY_LOW" not in codes
