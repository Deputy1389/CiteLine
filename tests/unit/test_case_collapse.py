from __future__ import annotations

from apps.worker.steps.case_collapse import (
    build_case_collapse_candidates,
    build_defense_attack_paths,
    build_objection_profiles,
    build_upgrade_recommendations,
    defense_narrative_for_candidate,
    quote_lock,
)


def _row(
    claim_type: str,
    assertion: str,
    *,
    date: str = "2025-01-01",
    citations: list[str] | None = None,
    flags: list[str] | None = None,
) -> dict:
    return {
        "claim_type": claim_type,
        "assertion": assertion,
        "date": date,
        "citations": citations or ["packet.pdf p. 5", "packet.pdf p. 6"],
        "flags": flags or [],
        "support_score": 3,
    }


def test_quote_lock_wraps_and_trims():
    q = quote_lock("  Patient reports severe neck pain after MVA.  ")
    assert q.startswith('"')
    assert q.endswith('"')
    assert "Patient reports severe neck pain after MVA" in q


def test_quote_lock_removes_checkbox_artifacts():
    q = quote_lock("[X] MRI Cervical Spine [ ] CT Scan")
    assert "[X]" not in q
    assert "[ ]" not in q
    assert "MRI Cervical Spine" in q


def test_build_case_collapse_candidates_detects_preexisting_and_gap():
    rows = [
        _row("PRE_EXISTING_MENTION", "History of chronic neck pain.", flags=["pre_existing_overlap"]),
        _row("GAP_IN_CARE", "Treatment gap of 120 days identified.", date="2025-06-01"),
        _row("SYMPTOM", "Pain remains 8/10 with limited ROM."),
        _row("SYMPTOM", "Pain remains 7/10 with numbness."),
        _row("SYMPTOM", "Pain remains 6/10 with weakness."),
        _row("SYMPTOM", "Pain remains 7/10 with functional limitation."),
    ]
    cands = build_case_collapse_candidates(rows)
    types = {c["fragility_type"] for c in cands}
    assert "PRE_EXISTING_OVERLAP" in types
    assert "GAP_BEFORE_ESCALATION" in types


def test_attack_paths_and_upgrades_are_citation_backed():
    rows = [
        _row("PRE_EXISTING_MENTION", "History of chronic lumbar pain.", flags=["pre_existing_overlap"]),
        _row("GAP_IN_CARE", "Treatment gap of 90 days identified."),
        _row("PRE_EXISTING_MENTION", "Prior chronic lumbar pain noted.", flags=["pre_existing_overlap"]),
    ]
    cands = build_case_collapse_candidates(rows)
    attacks = build_defense_attack_paths(cands, limit=2)
    upgrades = build_upgrade_recommendations(cands, limit=2)
    assert attacks
    assert upgrades
    assert all(a.get("citations") for a in attacks)
    assert all(u.get("citations") for u in upgrades)


def test_defense_narrative_mapping_returns_specific_text():
    txt = defense_narrative_for_candidate({"fragility_type": "GAP_BEFORE_ESCALATION"})
    assert "Delay in documented care" in txt


def test_low_objective_candidate_suppressed_with_strong_objective_chain():
    rows = [
        _row("SYMPTOM", "Pain remains 7/10."),
        _row("SYMPTOM", "Pain remains 6/10."),
        _row("SYMPTOM", "Pain remains 5/10."),
        _row("SYMPTOM", "Pain remains 6/10 with numbness."),
        _row("IMAGING_FINDING", "MRI shows C5-6 disc protrusion."),
        _row("IMAGING_FINDING", "MRI shows foraminal narrowing."),
        _row("PROCEDURE", "Epidural steroid injection performed."),
        _row("PROCEDURE", "Repeat injection with fluoroscopy."),
    ]
    cands = build_case_collapse_candidates(rows)
    types = {c["fragility_type"] for c in cands}
    assert "LOW_OBJECTIVE_CORROBORATION" not in types


def test_objection_profiles_detect_foundation_and_best_evidence():
    rows = [
        {
            "id": "c1",
            "event_id": "e1",
            "claim_type": "IMAGING_FINDING",
            "date": "2025-04-10",
            "assertion": "MRI impression shows disc protrusion.",
            "citations": ["packet.pdf p. 10"],
            "support_score": 2,
            "support_strength": "Weak",
            "flags": [],
        },
        {
            "id": "c2",
            "event_id": "e2",
            "claim_type": "SYMPTOM",
            "date": "2025-04-11",
            "assertion": "Patient reports neck pain 8/10.",
            "citations": [],
            "support_score": 1,
            "support_strength": "Weak",
            "flags": ["timing_ambiguous"],
        },
    ]
    profiles = build_objection_profiles(rows, limit=10)
    assert profiles
    cats = {c for p in profiles for c in p.get("objection_types", [])}
    assert "foundation" in cats
    assert "best_evidence" in cats
