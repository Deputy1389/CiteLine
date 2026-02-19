from __future__ import annotations

from types import SimpleNamespace

from scripts.litigation_qa import build_litigation_checklist


def _entry(event_id: str, event_type: str, facts: list[str], citation: str = "packet.pdf p. 1", patient: str = "P1"):
    return SimpleNamespace(
        event_id=event_id,
        event_type_display=event_type,
        facts=facts,
        citation_display=citation,
        patient_label=patient,
        date_display="2025-01-01 (time not documented)",
        provider_display="Unknown",
    )


def _ctx(entries, page_text):
    return {
        "projection_entries": entries,
        "events": [],
        "missing_records_payload": {"gaps": []},
        "page_text_by_number": page_text,
        "source_pages": 120,
        "patient_scope_violations": [],
    }


def test_sem_gate_encounter_type_sanity_fails_for_outpatient_inpatient_overlabel():
    report = "\n".join(
        [
            "Top 10 Case-Driving Events",
            "Appendix E: Issue Flags",
            *(f"2025-01-0{i} | Encounter: Inpatient Progress | Citation(s): packet.pdf p. {i}" for i in range(1, 7)),
        ]
    )
    checklist = build_litigation_checklist(
        run_id="sem1",
        source_pdf="x.pdf",
        report_text=report,
        ctx=_ctx([_entry(f"e{i}", "Inpatient Progress", ["Routine outpatient follow-up."]) for i in range(6)], {1: "outpatient clinic follow-up"}),
    )
    assert checklist["quality_gates"]["Q_SEM_1_encounter_type_sanity"]["pass"] is False


def test_sem_gate_mechanism_required_when_present():
    report = "\n".join(
        [
            "Date of Injury: Not established from records",
            "Mechanism: Not established from records",
            "Top 10 Case-Driving Events",
            "Appendix E: Issue Flags",
        ]
    )
    checklist = build_litigation_checklist(
        run_id="sem2",
        source_pdf="x.pdf",
        report_text=report,
        ctx=_ctx([_entry("e1", "Emergency Visit", ["Emergency room visit note."])], {3: "Emergency department after motor vehicle collision."}),
    )
    assert checklist["quality_gates"]["Q_SEM_2_mechanism_required_when_present"]["pass"] is False


def test_sem_gate_procedure_specificity_requires_anchor_details():
    report = "\n".join(
        [
            "2025-01-01 | Encounter: Procedure/Surgery",
            "What Happened: Procedure milestone recorded.",
            "Citation(s): packet.pdf p. 10",
            "Top 10 Case-Driving Events",
            "Appendix E: Issue Flags",
        ]
    )
    checklist = build_litigation_checklist(
        run_id="sem3",
        source_pdf="x.pdf",
        report_text=report,
        ctx=_ctx(
            [_entry("e1", "Procedure/Surgery", ["Procedure milestone recorded."], "packet.pdf p. 10")],
            {10: "Fluoroscopy-guided interlaminar injection with Depo-Medrol and lidocaine. Complications: none."},
        ),
    )
    assert checklist["quality_gates"]["Q_SEM_3_procedure_specificity_when_anchors_present"]["pass"] is False


def test_sem_gate_dx_purity_detects_gibberish():
    report = "\n".join(
        [
            "Appendix B: Diagnoses/Problems (assessment/impression)",
            "• Difficult mission late kind random words.",
            "Appendix D: Patient-Reported Outcomes",
            "Top 10 Case-Driving Events",
            "Appendix E: Issue Flags",
        ]
    )
    checklist = build_litigation_checklist(
        run_id="sem4",
        source_pdf="x.pdf",
        report_text=report,
        ctx=_ctx([_entry("e1", "Follow-Up Visit", ["Assessment: cervical radiculopathy."])], {1: "clinic note"}),
    )
    assert checklist["quality_gates"]["Q_SEM_4_dx_purity"]["pass"] is False


def test_use_gate_placeholder_language_fails():
    report = "\n".join(
        [
            "Top 10 Case-Driving Events",
            "Appendix E: Issue Flags",
            "2025-01-01 | Encounter: Clinical Note | What Happened: encounter recorded.",
        ]
    )
    checklist = build_litigation_checklist(
        run_id="use1",
        source_pdf="x.pdf",
        report_text=report,
        ctx=_ctx([_entry("e1", "Clinical Note", ["Assessment: cervical radiculopathy."], "packet.pdf p. 1")], {1: "clinic note"}),
    )
    assert checklist["quality_gates"]["Q_USE_5_no_placeholder_language"]["pass"] is False


def test_use_gate_high_density_ratio_fails_when_low():
    entries = [
        _entry("e1", "Clinical Note", ["Brief follow-up."], "packet.pdf p. 1"),
        _entry("e2", "Clinical Note", ["Routine check."], "packet.pdf p. 2"),
        _entry("e3", "Clinical Note", ["General note."], "packet.pdf p. 3"),
        _entry("e4", "Clinical Note", ["Another general note."], "packet.pdf p. 4"),
        _entry("e5", "Clinical Note", ["Context only."], "packet.pdf p. 5"),
    ]
    report = "Top 10 Case-Driving Events\nAppendix E: Issue Flags\n"
    checklist = build_litigation_checklist(
        run_id="use2",
        source_pdf="x.pdf",
        report_text=report,
        ctx=_ctx(entries, {1: "clinic note"}),
    )
    assert checklist["quality_gates"]["Q_USE_HIGH_DENSITY_RATIO"]["pass"] is False


def test_use_gate_verbatim_snippets_fails_when_missing():
    report = "Top 10 Case-Driving Events\nAppendix E: Issue Flags\nWhat Happened: no quotes here\n"
    checklist = build_litigation_checklist(
        run_id="use3",
        source_pdf="x.pdf",
        report_text=report,
        ctx=_ctx([_entry("e1", "Emergency Visit", ["Chief complaint: neck pain"], "packet.pdf p. 1")], {1: "ed note"}),
    )
    assert checklist["quality_gates"]["Q_USE_VERBATIM_SNIPPETS"]["pass"] is False


def test_final_render_consistency_flags_summary_timeline_mismatch_and_dot_pdf():
    report = "\n".join(
        [
            "Total Surgeries: 0",
            "No surgeries documented.",
            "2025-01-01 | Encounter: Procedure/Surgery",
            "Citation(s): packet. pdf p. 10",
            "2025-01-02 | Encounter: Emergency Visit",
            "Citation(s): packet. pdf p. 11",
            "2025-01-03 | Encounter: Imaging Study",
            "Citation(s): packet. pdf p. 12",
            "2025-01-04 | Encounter: Orthopedic Consult",
            "Citation(s): packet. pdf p. 13",
            "Top 10 Case-Driving Events",
            "• 2025-01-01 | Procedure/Surgery | x | Citation(s): packet. pdf p. 10",
            "Appendix A:",
        ]
    )
    entries = [
        _entry("e1", "Procedure/Surgery", ["Procedure: epidural injection"], "packet.pdf p. 10"),
        _entry("e2", "Emergency Visit", ['Chief Complaint: "neck pain"'], "packet.pdf p. 11"),
        _entry("e3", "Imaging Study", ['Impression: "disc protrusion"'], "packet.pdf p. 12"),
        _entry("e4", "Orthopedic Consult", ['Assessment: "radiculopathy". Plan: "PT".'], "packet.pdf p. 13"),
    ]
    checklist = build_litigation_checklist(
        run_id="render1",
        source_pdf="x.pdf",
        report_text=report,
        ctx=_ctx(entries, {1: "ed", 2: "mri impression", 3: "ortho assessment plan", 4: "procedure depo-medrol lidocaine"}),
    )
    gate = checklist["quality_gates"]["Q_FINAL_RENDER_CONSISTENCY"]
    assert gate["pass"] is False
    codes = {d["code"] for d in gate["details"]}
    assert "SUMMARY_TIMELINE_PROCEDURE_MISMATCH" in codes
    assert "DOT_PDF_SPACING_RENDERED" in codes


def test_top10_row_without_inline_citation_fails_usability_gate():
    report = "\n".join(
        [
            "2025-01-01 | Encounter: Emergency Visit",
            "Citation(s): packet.pdf p. 10",
            "Top 10 Case-Driving Events",
            "- 2025-01-01 | Emergency Visit | chief complaint neck pain",
            "Appendix A: Medications",
            "Appendix E: Issue Flags",
        ]
    )
    entries = [_entry("e1", "Emergency Visit", ['Chief Complaint: "neck pain"'], "packet.pdf p. 10")]
    checklist = build_litigation_checklist(
        run_id="render2",
        source_pdf="x.pdf",
        report_text=report,
        ctx=_ctx(entries, {1: "ed note mvc"}),
    )
    gate = checklist["quality_gates"]["Q8_attorney_usability_sections"]
    assert gate["pass"] is False
    codes = {d["code"] for d in gate["details"]}
    assert "TOP10_ITEM_MISSING_CITATION" in codes


def test_use_required_buckets_counts_procedure_from_anchor_facts_even_without_procedure_label():
    report = "\n".join(
        [
            "Top 10 Case-Driving Events",
            "Appendix E: Issue Flags",
        ]
    )
    entries = [
        _entry(
            "e1",
            "Orthopedic Consult",
            [
                "Plan: consider epidural injection.",
                "Fluoroscopy-guided injection with Depo-Medrol and lidocaine documented.",
            ],
            "packet.pdf p. 55",
        )
    ]
    checklist = build_litigation_checklist(
        run_id="use4",
        source_pdf="x.pdf",
        report_text=report,
        ctx=_ctx(entries, {1: "Depo-Medrol lidocaine fluoroscopy interlaminar injection"}),
    )
    gate = checklist["quality_gates"]["Q_USE_1_required_buckets_present"]
    assert gate["metrics"].get("procedure", 0) >= 1


def test_use_required_buckets_does_not_require_procedure_on_single_weak_anchor():
    report = "\n".join(
        [
            "Top 10 Case-Driving Events",
            "Appendix E: Issue Flags",
        ]
    )
    entries = [_entry("e1", "Orthopedic Consult", ["Assessment: cervical pain"], "packet.pdf p. 10")]
    checklist = build_litigation_checklist(
        run_id="use5",
        source_pdf="x.pdf",
        report_text=report,
        ctx=_ctx(entries, {1: "Provider note mentions lidocaine patch only."}),
    )
    gate = checklist["quality_gates"]["Q_USE_1_required_buckets_present"]
    detail_codes = {d.get("code") for d in gate.get("details", [])}
    assert "USE_REQUIRED_BUCKETS_MISSING" not in detail_codes
