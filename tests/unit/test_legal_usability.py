from __future__ import annotations

from apps.worker.lib.legal_usability import build_legal_usability_report


def test_legal_usability_fails_when_luqa_or_attorney_fail() -> None:
    report = (
        "Chronological Medical Timeline\n"
        "2025-01-01 | Encounter: Emergency Visit\nChief Complaint: \"MVC neck pain\"\nCitation(s): p. 1\n"
        "Liability Facts\n- 2025-01-01 | Mechanism: MVC rear-end collision | Citation(s): p. 1\n"
        "Causation Chain\n- 2025-01-02 | Imaging supports acute injury | Citation(s): p. 2\n"
        "Damages Progression\n- 2025-01-03 | Pain 8/10 and ROM 20 deg | Citation(s): p. 3\n"
        "Top 10 Case-Driving Events\n"
    )
    ctx = {"page_text_by_number": {1: "Emergency department chief complaint after MVC"}}
    out = build_legal_usability_report(
        report,
        ctx,
        {"luqa_pass": False, "luqa_score_0_100": 60, "failures": [{"code": "LUQA_X"}]},
        {"attorney_ready_pass": True, "attorney_ready_score_0_100": 100, "failures": []},
    )
    assert out["legal_pass"] is False
    assert any(f["code"] == "LEGAL_LUQA_FAILED" for f in out["failures"])


def test_legal_usability_requires_mechanism_when_ed_present() -> None:
    report = (
        "Chronological Medical Timeline\n"
        "2025-01-01 | Encounter: Emergency Visit\nChief Complaint: \"neck pain\"\nCitation(s): p. 1\n"
        "Liability Facts\n- 2025-01-01 | Mechanism: neck pain only | Citation(s): p. 1\n"
        "Causation Chain\n- 2025-01-02 | Imaging supports symptoms | Citation(s): p. 2\n"
        "Damages Progression\n- 2025-01-03 | Pain 7/10 ROM 30 deg | Citation(s): p. 3\n"
        "Top 10 Case-Driving Events\n"
    )
    ctx = {"page_text_by_number": {1: "Emergency department triage and HPI for motor vehicle collision"}}
    out = build_legal_usability_report(
        report,
        ctx,
        {"luqa_pass": True, "luqa_score_0_100": 95, "failures": []},
        {"attorney_ready_pass": True, "attorney_ready_score_0_100": 95, "failures": []},
    )
    assert out["legal_pass"] is False
    assert any(f["code"] == "LEGAL_MISSING_MECHANISM_CHAIN" for f in out["failures"])


def test_legal_usability_passes_when_chains_present() -> None:
    report = (
        "Chronological Medical Timeline\n"
        "2025-01-01 | Encounter: Emergency Visit\n"
        "Chief Complaint: \"rear-end motor vehicle collision with neck pain 8/10\"\n"
        "Citation(s): p. 1\n"
        "Liability Facts\n"
        "- 2025-01-01 | Mechanism: rear-end motor vehicle collision | Citation(s): p. 1\n"
        "Causation Chain\n"
        "- 2025-01-10 | MRI C5-6 protrusion followed by procedure escalation | Citation(s): p. 2\n"
        "Damages Progression\n"
        "- 2025-01-17 | Pain 8/10; ROM 20 deg; Strength 4/5 | Citation(s): p. 3\n"
        "2025-01-10 | Encounter: Procedure\n"
        "Procedure: \"Epidural injection with fluoroscopy and lidocaine\"\n"
        "Citation(s): p. 2\n"
        "2025-01-17 | Encounter: Therapy Visit\n"
        "PT Summary: \"Pain: 8/10; ROM: 20 deg; Strength: 4/5\"\n"
        "Citation(s): p. 3\n"
        "Top 10 Case-Driving Events\n"
    )
    ctx = {
        "page_text_by_number": {
            1: "Emergency department HPI after motor vehicle collision",
            2: "Depo-Medrol lidocaine fluoroscopy interlaminar",
            3: "PT eval ROM and strength",
        }
    }
    out = build_legal_usability_report(
        report,
        ctx,
        {"luqa_pass": True, "luqa_score_0_100": 93, "failures": []},
        {"attorney_ready_pass": True, "attorney_ready_score_0_100": 97, "failures": []},
    )
    assert out["legal_pass"] is True
    assert out["legal_score_0_100"] >= 90


def test_legal_usability_fails_when_case_theory_sections_missing() -> None:
    report = (
        "Chronological Medical Timeline\n"
        "2025-01-01 | Encounter: Emergency Visit\n"
        "Chief Complaint: \"rear-end motor vehicle collision with neck pain 8/10\"\n"
        "Citation(s): p. 1\n"
        "Top 10 Case-Driving Events\n"
    )
    ctx = {"page_text_by_number": {1: "Emergency department HPI after motor vehicle collision"}}
    out = build_legal_usability_report(
        report,
        ctx,
        {"luqa_pass": True, "luqa_score_0_100": 95, "failures": []},
        {"attorney_ready_pass": True, "attorney_ready_score_0_100": 95, "failures": []},
    )
    assert out["legal_pass"] is False
    assert any(f["code"] == "LEGAL_MISSING_CASE_THEORY_SECTIONS" for f in out["failures"])


def test_legal_usability_fails_on_low_value_top10_snippets() -> None:
    report = (
        "Chronological Medical Timeline\n"
        "2025-01-01 | Encounter: Emergency Visit\n"
        "Chief Complaint: \"rear-end motor vehicle collision with neck pain 8/10\"\n"
        "Citation(s): p. 1\n"
        "Liability Facts\n- 2025-01-01 | Mechanism: rear-end MVC | Citation(s): p. 1\n"
        "Causation Chain\n- 2025-01-10 | MRI findings followed by procedure | Citation(s): p. 2\n"
        "Damages Progression\n- 2025-01-17 | Pain 8/10; ROM 20 deg; Strength 4/5 | Citation(s): p. 3\n"
        "Top 10 Case-Driving Events\n"
        "- 2025-01-10 | Procedure/Surgery | INFORMED CONSENT FOR PROCEDURE ... | Citation(s): p. 2\n"
        "Appendix A: Medications\n"
    )
    ctx = {"page_text_by_number": {1: "Emergency department HPI after motor vehicle collision"}}
    out = build_legal_usability_report(
        report,
        ctx,
        {"luqa_pass": True, "luqa_score_0_100": 95, "failures": []},
        {"attorney_ready_pass": True, "attorney_ready_score_0_100": 95, "failures": []},
    )
    assert out["legal_pass"] is False
    assert any(f["code"] == "LEGAL_LOW_VALUE_SNIPPET_LEAK" for f in out["failures"])


def test_legal_usability_fails_on_artifact_text_leak() -> None:
    report = (
        "Chronological Medical Timeline\n"
        "Liability Facts\n- 2025-01-01 | Mechanism: Impact was BP | Citation(s): p. 1\n"
        "Causation Chain\n- 2025-01-02 | Chain line | Citation(s): p. 2\n"
        "Damages Progression\n- 2025-01-03 | Pain 8/10 ROM 20 deg | Citation(s): p. 3\n"
        "Top 10 Case-Driving Events\n"
        "- 2025-01-03 | Imaging Study | [X] MRI finding line. | Citation(s): p. 3\n"
        "Appendix A: Medications\n"
    )
    ctx = {"page_text_by_number": {1: "Emergency department HPI after motor vehicle collision"}}
    out = build_legal_usability_report(
        report,
        ctx,
        {"luqa_pass": True, "luqa_score_0_100": 95, "failures": []},
        {"attorney_ready_pass": True, "attorney_ready_score_0_100": 95, "failures": []},
    )
    assert out["legal_pass"] is False
    assert any(f["code"] == "LEGAL_ARTIFACT_TEXT_LEAK" for f in out["failures"])
