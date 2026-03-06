from __future__ import annotations

from types import SimpleNamespace

from apps.worker.lib.luqa import build_luqa_report


def _entry(
    date_display: str,
    facts: list[str],
    citation_display: str = "packet.pdf p. 1",
    *,
    event_type_display: str = "Clinical Note",
    provider_display: str = "Unknown",
    verbatim_flags: list[bool] | None = None,
):
    return SimpleNamespace(
        date_display=date_display,
        facts=facts,
        citation_display=citation_display,
        event_type_display=event_type_display,
        provider_display=provider_display,
        verbatim_flags=verbatim_flags or [False] * len(facts),
    )


def _ctx(entries=None, page_text=None):
    return {
        "projection_entries": entries or [],
        "page_text_by_number": page_text or {},
    }


def test_luqa_meta_language_ban_triggers():
    report = """
Chronological Medical Timeline
2025-01-01 | Encounter: Clinical Note
Facility/Clinician: Unknown
"Emergency-care encounter identified from source ED/HPI markers."
Citation(s): packet.pdf p. 1
Top 10 Case-Driving Events
"""
    luqa = build_luqa_report(report, _ctx())
    assert luqa["luqa_pass"] is False
    codes = {f["code"] for f in luqa["failures"]}
    assert "LUQA_META_LANGUAGE_BAN" in codes


def test_luqa_duplicate_snippets_triggers_on_triplicate():
    report = """
Chronological Medical Timeline
2025-01-01 | Encounter: Therapy Visit
Facility/Clinician: PT
"Cervical ROM: Flexion 30 deg, Extension 20 deg."
Citation(s): packet.pdf p. 10
2025-01-01 | Encounter: Therapy Visit
Facility/Clinician: PT
"Cervical ROM: Flexion 30 deg, Extension 20 deg."
Citation(s): packet.pdf p. 11
2025-01-01 | Encounter: Therapy Visit
Facility/Clinician: PT
"Cervical ROM: Flexion 30 deg, Extension 20 deg."
Citation(s): packet.pdf p. 12
Top 10 Case-Driving Events
"""
    luqa = build_luqa_report(report, _ctx())
    codes = {f["code"] for f in luqa["failures"]}
    assert "LUQA_DUPLICATE_SNIPPETS" in codes


def test_luqa_care_window_mismatch_triggers():
    report = """
Treatment Timeframe: 2025-01-01 to 2025-01-15
Chronological Medical Timeline
2025-01-20 | Encounter: Imaging Study
Facility/Clinician: Radiology
"Impression: C5-6 disc protrusion with mild foraminal narrowing."
Citation(s): packet.pdf p. 2
Top 10 Case-Driving Events
"""
    entries = [_entry("2025-01-20 (time not documented)", ["Impression: C5-6 disc protrusion with mild foraminal narrowing."])]
    luqa = build_luqa_report(report, _ctx(entries=entries))
    codes = {f["code"] for f in luqa["failures"]}
    assert "LUQA_CARE_WINDOW_INTEGRITY" in codes


def test_luqa_required_buckets_when_present_triggers():
    report = """
Chronological Medical Timeline
2025-01-02 | Encounter: Imaging Study
Facility/Clinician: Radiology
"Impression: C5-6 disc protrusion."
Citation(s): packet.pdf p. 3
Top 10 Case-Driving Events
"""
    page_text = {1: "Emergency Department triage and HPI after MVC."}
    luqa = build_luqa_report(report, _ctx(page_text=page_text))
    codes = {f["code"] for f in luqa["failures"]}
    assert "LUQA_REQUIRED_BUCKETS_WHEN_PRESENT" in codes


def test_luqa_bucket_presence_uses_projection_fallback_when_pdf_rows_are_sparse():
    report = """
Chronological Medical Timeline
2025-01-02 | Encounter: Clinical Note
Facility/Clinician: Unknown
"Neck pain 8/10."
Citation(s): packet.pdf p. 3
Top 10 Case-Driving Events
"""
    page_text = {1: "MRI impression: C5-6 disc protrusion with foraminal narrowing."}
    entries = [
        _entry(
            "2025-01-02 (time not documented)",
            ["MRI cervical spine impression: C5-6 disc protrusion with foraminal narrowing."],
            "packet.pdf p. 3",
        )
    ]
    luqa = build_luqa_report(report, _ctx(entries=entries, page_text=page_text))
    codes = {f["code"] for f in luqa["failures"]}
    assert "LUQA_REQUIRED_BUCKETS_WHEN_PRESENT" not in codes


def test_luqa_placeholder_ratio_triggers():
    report = """
Chronological Medical Timeline
2025-01-01 | Encounter: Clinical Note
Facility/Clinician: Unknown
"Clinical documentation recorded."
Citation(s): packet.pdf p. 1
2025-01-02 | Encounter: Clinical Note
Facility/Clinician: Unknown
"Limited detail."
Citation(s): packet.pdf p. 2
2025-01-03 | Encounter: Clinical Note
Facility/Clinician: Unknown
"Neck pain 8/10 after MVC with Toradol 30 mg and C5-6 findings."
Citation(s): packet.pdf p. 3
Top 10 Case-Driving Events
"""
    luqa = build_luqa_report(report, _ctx())
    codes = {f["code"] for f in luqa["failures"]}
    assert "LUQA_PLACEHOLDER_RATIO" in codes


def test_luqa_render_quality_sanity_triggers_on_undated_top10_and_dx_pollution():
    report = """
Chronological Medical Timeline
2025-01-01 | Encounter: Emergency Visit
Facility/Clinician: Unknown
Chief Complaint: "Patient presents with neck pain after MVC.".
Citation(s): packet.pdf p. 1
Top 10 Case-Driving Events
\x7f Date not documented | Hospital Discharge | DISCHARGE SUMMARY line. | Citation(s): p. 2.
Appendix B: Diagnoses/Problems (assessment/impression)
DISCHARGE SUMMARY Discharge Summary Pain Level: Final Pain: 2/10.
"""
    luqa = build_luqa_report(report, _ctx())
    codes = {f["code"] for f in luqa["failures"]}
    assert "LUQA_RENDER_QUALITY_SANITY" in codes


def test_luqa_render_quality_sanity_triggers_on_ortho_missing_plan_and_truncated_fragment():
    report = """
Chronological Medical Timeline
2025-01-01 | Encounter: Orthopedic Consult
Facility/Clinician: Unknown
Assessment: "Persistent cervical radiculopathy and weakness includ"
Citation(s): packet.pdf p. 10
Top 10 Case-Driving Events
- 2025-01-01 | Orthopedic Consult | symptoms improved and.
Appendix A:
"""
    luqa = build_luqa_report(report, _ctx())
    codes = {f["code"] for f in luqa["failures"]}
    assert "LUQA_RENDER_QUALITY_SANITY" in codes


def test_luqa_verbatim_ratio_uses_structured_verbatim_flags():
    report = "Medical Timeline (Litigation Ready)\nTop 10 Case-Driving Events\n"
    entries = [
        _entry(
            "2025-01-01",
            ["Chief complaint: rear-end MVC with neck pain 8/10."],
            "packet.pdf p. 1",
            event_type_display="Emergency Visit",
            verbatim_flags=[True],
        ),
        _entry(
            "2025-01-02",
            ["Assessment: cervical strain and limited ROM."],
            "packet.pdf p. 2",
            event_type_display="Follow-Up Visit",
            verbatim_flags=[False],
        ),
    ]
    luqa = build_luqa_report(report, _ctx(entries=entries))
    assert luqa["metrics"]["qa_rows_source"] == "projection_rows"
    assert luqa["metrics"]["verbatim_ratio"] > 0


def test_luqa_projection_bucket_presence_recognizes_ed_from_event_type():
    report = "Medical Timeline (Litigation Ready)\nTop 10 Case-Driving Events\n"
    page_text = {1: "Emergency Department triage and HPI after MVC."}
    entries = [
        _entry(
            "2025-01-01",
            ["General Hospital & Trauma Center 8/10"],
            "packet.pdf p. 1",
            event_type_display="Emergency Visit",
            verbatim_flags=[False],
        )
    ]
    luqa = build_luqa_report(report, _ctx(entries=entries, page_text=page_text))
    codes = {f["code"] for f in luqa["failures"]}
    assert "LUQA_REQUIRED_BUCKETS_WHEN_PRESENT" not in codes


def test_luqa_timeline_slice_stops_before_billing_diagnostics() -> None:
    report = """
Medical Chronology Analysis
CASE SNAPSHOT (30-SECOND READ)
Top 10 Case-Driving Events
- 2025-01-01 | Emergency Visit | neck pain after MVC. | Citation(s): p. 1
Medical Timeline (Litigation Ready)
2025-01-01 | Encounter: Emergency Visit
Facility/Clinician: General Hospital
"Chief complaint: neck pain after MVC."
Citation(s): packet.pdf p. 1
Billing / Specials
Billing extraction status: No billing data extracted from packet.
Billing pages detected: 0
Flags: NO_BILLING_DATA
Appendix A:
"""
    entries = [
        _entry(
            "2025-01-01",
            ['Chief complaint: neck pain after MVC.'],
            "packet.pdf p. 1",
            event_type_display="Emergency Visit",
            verbatim_flags=[True],
        )
    ]

    luqa = build_luqa_report(report, _ctx(entries=entries))
    codes = {f["code"] for f in luqa["failures"]}

    assert "LUQA_META_LANGUAGE_BAN" not in codes


def test_luqa_relaxes_density_and_verbatim_soft_gates_for_compact_packets() -> None:
    report = """
Medical Chronology Analysis
Medical Timeline (Litigation Ready)
2025-01-01 | Encounter: Emergency Visit
Facility/Clinician: General Hospital
Chief complaint: neck pain after MVC.
Citation(s): packet.pdf p. 1
Billing / Specials
Appendix A:
"""
    entries = [
        _entry(
            "2025-01-01",
            ["Chief complaint: neck pain after MVC."],
            "packet.pdf p. 1",
            event_type_display="Emergency Visit",
            verbatim_flags=[False],
        )
    ]

    luqa = build_luqa_report(report, _ctx(entries=entries, page_text={1: "Emergency Department triage after MVC."}))
    codes = {f["code"] for f in luqa["failures"]}

    assert "LUQA_FACT_DENSITY" not in codes
    assert "LUQA_VERBATIM_ANCHOR_RATIO" not in codes
