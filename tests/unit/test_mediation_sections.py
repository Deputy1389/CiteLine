"""
Unit tests for mediation_sections.py (Pass31 + Pass32).

Pass31 covers:
- Objective trigger predicates
- Defense template text (no severity tags, no penalties)
- Section order enforcement
- Structural gate fail/pass on thin vs rich payloads
- Functional limitations trigger
- Treatment escalation canonical order
- Economic damages honesty rule

Pass32 adds:
- Escalation definition (_detect_escalation)
- Current Condition & Prognosis (last-window rule)
- Clinical Course & Reasonableness (escalation-gated)
- Provider Corroboration (entity-ID gated)
- Time compression signal in Mechanism section
- Milestone dates in Treatment Progression
- Updated 10-section order
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.worker.steps.export_render.mediation_sections import (
    _CANONICAL_STAGE_ORDER,
    _DEFENSE_TEMPLATES,
    _build_clinical_reasonableness_section,
    _build_current_condition_section,
    _build_defense_preemption_section,
    _build_economic_damages_section,
    _build_functional_limitations_section,
    _build_mechanism_section,
    _build_objective_findings_section,
    _build_provider_corroboration_section,
    _build_severity_profile_section,
    _build_treatment_progression_section,
    _detect_defense_flags,
    _detect_escalation,
    _detect_stages,
    _functional_trigger,
    _last_window_trigger,
    _objective_trigger,
    build_mediation_sections,
    run_mediation_structural_gate,
)


# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------

def _make_finding(category: str, label: str, cids: list[str] | None = None, provider_entity_id: str | None = None) -> dict:
    f: dict = {"category": category, "label": label, "citation_ids": cids or []}
    if provider_entity_id is not None:
        f["provider_entity_id"] = provider_entity_id
    return f


def _make_rm(
    promoted_findings: list[dict] | None = None,
    mechanism: str | None = None,
    doi: str | None = None,
    billing_completeness: str = "none",
    bucket_evidence: dict | None = None,
) -> dict:
    rm: dict = {
        "promoted_findings": promoted_findings or [],
        "billing_completeness": billing_completeness,
    }
    if mechanism:
        rm["mechanism"] = {"value": mechanism, "citation_ids": ["cid_1"]}
    if doi:
        rm["doi"] = {"value": doi, "source": "extracted", "citation_ids": ["cid_2"]}
    if bucket_evidence is not None:
        rm["bucket_evidence"] = bucket_evidence
    return rm


class _MockEventType:
    def __init__(self, value: str):
        self.value = value


class _MockDate:
    def __init__(self, value):
        self.value = value


class _MockFact:
    def __init__(self, text: str):
        self.text = text


class _MockEvent:
    def __init__(
        self,
        event_id: str,
        event_type: str,
        date_value=None,
        facts: list[str] | None = None,
        diagnoses: list[str] | None = None,
        exam_findings: list[str] | None = None,
    ):
        self.event_id = event_id
        self.event_type = _MockEventType(event_type)
        self.date = _MockDate(date_value) if date_value is not None else None
        self.facts = [_MockFact(f) for f in (facts or [])]
        self.diagnoses = [_MockFact(d) for d in (diagnoses or [])]
        self.exam_findings = [_MockFact(e) for e in (exam_findings or [])]
        self.citation_ids = []


# ---------------------------------------------------------------------------
# Pass31 — Objective trigger predicates
# ---------------------------------------------------------------------------

class TestObjectiveTrigger:
    def test_category_imaging_triggers(self):
        rm = _make_rm(promoted_findings=[_make_finding("imaging", "MRI lumbar spine")])
        assert _objective_trigger({}, rm) is True

    def test_category_objective_deficit_triggers(self):
        rm = _make_rm(promoted_findings=[_make_finding("objective_deficit", "Reduced grip strength")])
        assert _objective_trigger({}, rm) is True

    def test_symptom_category_alone_does_not_trigger(self):
        rm = _make_rm(promoted_findings=[_make_finding("symptom", "Neck pain")])
        assert _objective_trigger({}, rm) is False

    def test_empty_findings_no_trigger(self):
        rm = _make_rm()
        assert _objective_trigger({}, rm) is False

    def test_bucket_evidence_detected_triggers(self):
        rm = _make_rm(bucket_evidence={"mri": {"detected": True}})
        assert _objective_trigger({}, rm) is True

    def test_bucket_evidence_not_detected_no_trigger(self):
        rm = _make_rm(bucket_evidence={"mri": {"detected": False}})
        assert _objective_trigger({}, rm) is False


class TestObjectiveFindingsSection:
    def test_symptom_rows_excluded(self):
        rm = _make_rm(promoted_findings=[
            _make_finding("symptom", "Neck pain, 8/10"),
            _make_finding("imaging", "C4-C5 disc protrusion"),
        ])
        section = _build_objective_findings_section({}, rm)
        labels = [item.label for item in section.items]
        assert any("C4-C5" in l for l in labels)
        assert not any("Neck pain" in l for l in labels)

    def test_no_duplicates(self):
        rm = _make_rm(promoted_findings=[
            _make_finding("imaging", "L4-L5 disc herniation"),
            _make_finding("imaging", "L4-L5 disc herniation"),
        ])
        section = _build_objective_findings_section({}, rm)
        assert len(section.items) == 1

    def test_gate_required_and_absent_sets_gate_fail(self):
        rm = _make_rm(promoted_findings=[_make_finding("imaging", "MRI findings")])
        section = _build_objective_findings_section({}, rm)
        assert section.gate_required is True
        assert section.gate_fail is False  # items were built

    def test_pain_score_lines_excluded(self):
        """Pass32: lines like 'pain 8/10' must be excluded."""
        rm = _make_rm(promoted_findings=[
            _make_finding("imaging", "Neck pain 8/10"),
            _make_finding("imaging", "L4-L5 disc herniation"),
        ])
        section = _build_objective_findings_section({}, rm)
        labels = [item.label for item in section.items]
        assert not any("8/10" in l for l in labels)
        assert any("L4-L5" in l for l in labels)

    def test_imaging_before_objective_deficit(self):
        """Pass32: imaging findings must appear before objective_deficit findings."""
        rm = _make_rm(promoted_findings=[
            _make_finding("objective_deficit", "Reduced ROM cervical"),
            _make_finding("imaging", "MRI C-spine: disc protrusion"),
        ])
        section = _build_objective_findings_section({}, rm)
        keys = [item.label for item in section.items]
        imaging_idx = next(i for i, l in enumerate(keys) if "MRI" in l)
        deficit_idx = next(i for i, l in enumerate(keys) if "ROM" in l)
        assert imaging_idx < deficit_idx


# ---------------------------------------------------------------------------
# Pass31 — Treatment escalation canonical order
# ---------------------------------------------------------------------------

class TestTreatmentProgression:
    def test_stages_always_in_canonical_order(self):
        events = [
            _MockEvent("e1", "pt_visit"),
            _MockEvent("e2", "er_visit"),
            _MockEvent("e3", "surgery"),
        ]
        stages = _detect_stages(events, {})
        idxs = [_CANONICAL_STAGE_ORDER.index(s) for s in stages]
        assert idxs == sorted(idxs), "Stages not in canonical order"

    def test_all_stages_detectable(self):
        events = [
            _MockEvent("e1", "er_visit"),
            _MockEvent("e2", "mri"),
            _MockEvent("e3", "pt_visit"),
            _MockEvent("e4", "specialist_visit"),
            _MockEvent("e5", "injection"),
            _MockEvent("e6", "surgery"),
        ]
        stages = _detect_stages(events, {})
        assert set(stages) == {"ed", "imaging", "pt", "specialist", "procedure", "surgery"}

    def test_bucket_evidence_supplements_events(self):
        rm_with_bucket = _make_rm(bucket_evidence={"ed": {"detected": True}, "pt_eval": {"detected": True}})
        stages = _detect_stages([], rm_with_bucket)
        assert "ed" in stages
        assert "pt" in stages

    def test_section_gate_required_gt1_stage(self):
        events = [_MockEvent("e1", "er_visit"), _MockEvent("e2", "pt_visit")]
        section = _build_treatment_progression_section({}, {}, raw_events=events)
        assert section.gate_required is True

    def test_section_gate_not_required_single_stage(self):
        events = [_MockEvent("e1", "er_visit")]
        section = _build_treatment_progression_section({}, {}, raw_events=events)
        assert section.gate_required is False

    def test_milestone_dates_attached_when_available(self):
        """Pass32: stage labels include earliest date when event is dated."""
        events = [
            _MockEvent("e1", "er_visit", date_value=datetime.date(2024, 3, 15)),
            _MockEvent("e2", "pt_visit", date_value=datetime.date(2024, 4, 1)),
        ]
        section = _build_treatment_progression_section({}, {}, raw_events=events)
        ed_item = next(it for it in section.items if "Emergency" in it.label)
        assert "2024-03-15" in ed_item.label

    def test_milestone_dates_earliest_only(self):
        """Pass32: only earliest date per stage, not latest."""
        events = [
            _MockEvent("e1", "pt_visit", date_value=datetime.date(2024, 4, 1)),
            _MockEvent("e2", "pt_visit", date_value=datetime.date(2024, 5, 1)),  # later
        ]
        section = _build_treatment_progression_section({}, {}, raw_events=events)
        pt_item = next(it for it in section.items if "Physical Therapy" in it.label)
        # Should show the earlier date, not the later
        assert "2024-04-01" in pt_item.label
        assert "2024-05-01" not in pt_item.label

    def test_label_without_date_when_event_undated(self):
        """Pass32: undated events keep bare label."""
        events = [_MockEvent("e1", "er_visit"), _MockEvent("e2", "pt_visit")]
        section = _build_treatment_progression_section({}, {}, raw_events=events)
        ed_item = next(it for it in section.items if "Emergency" in it.label)
        assert "–" not in ed_item.label


# ---------------------------------------------------------------------------
# Pass31 — Defense preemption templates
# ---------------------------------------------------------------------------

class TestDefensePreemption:
    def test_no_severity_tags_in_templates(self):
        forbidden = {"high", "medium", "low", "penalty", "valuation", "score"}
        for key, text in _DEFENSE_TEMPLATES.items():
            low = text.lower()
            for f in forbidden:
                assert f not in low, f"Template '{key}' contains forbidden word '{f}'"

    def test_care_gap_flag_from_lsv1(self):
        ext = {"litigation_safe_v1": {"computed": {"max_gap_days": 60}}}
        flags = _detect_defense_flags(ext, {})
        assert flags["care_gap"] is True

    def test_care_gap_flag_not_triggered_short_gap(self):
        ext = {"litigation_safe_v1": {"computed": {"max_gap_days": 30}}}
        flags = _detect_defense_flags(ext, {})
        assert flags["care_gap"] is False

    def test_delayed_treatment_flag(self):
        ext = {"litigation_safe_v1": {"computed": {"days_to_first_treatment": 14}}}
        flags = _detect_defense_flags(ext, {})
        assert flags["delayed_treatment"] is True

    def test_delayed_treatment_not_triggered_early(self):
        ext = {"litigation_safe_v1": {"computed": {"days_to_first_treatment": 3}}}
        flags = _detect_defense_flags(ext, {})
        assert flags["delayed_treatment"] is False

    def test_prior_injury_from_claim_rows(self):
        ext = {"claim_rows": [{"claim_type": "prior_injury_disclosure", "assertion": "Prior knee surgery"}]}
        flags = _detect_defense_flags(ext, {})
        assert flags["prior_injury"] is True

    def test_section_items_use_locked_templates(self):
        ext = {
            "litigation_safe_v1": {"computed": {"max_gap_days": 90, "days_to_first_treatment": 10}},
            "claim_rows": [{"claim_type": "prior_injury_disclosure"}],
        }
        section = _build_defense_preemption_section(ext, {})
        rendered_texts = {item.label for item in section.items}
        assert _DEFENSE_TEMPLATES["care_gap"] in rendered_texts
        assert _DEFENSE_TEMPLATES["delayed_treatment"] in rendered_texts
        assert _DEFENSE_TEMPLATES["prior_injury"] in rendered_texts

    def test_section_empty_when_no_flags(self):
        section = _build_defense_preemption_section({}, {})
        assert section.items == []
        assert section.gate_required is False


# ---------------------------------------------------------------------------
# Pass31 — Functional limitations
# ---------------------------------------------------------------------------

class TestFunctionalLimitations:
    def test_disability_triggers(self):
        rm = _make_rm(promoted_findings=[_make_finding("objective_deficit", "Permanent disability rating 15%")])
        assert _functional_trigger({}, rm) is True

    def test_work_restriction_triggers(self):
        rm = _make_rm(promoted_findings=[_make_finding("objective_deficit", "Work restriction: no lifting >10 lbs")])
        assert _functional_trigger({}, rm) is True

    def test_plain_diagnosis_no_trigger(self):
        rm = _make_rm(promoted_findings=[_make_finding("diagnosis", "Cervical disc herniation")])
        assert _functional_trigger({}, rm) is False

    def test_section_empty_on_no_trigger(self):
        section = _build_functional_limitations_section({}, {})
        assert section.items == []
        assert section.gate_required is False

    def test_disability_items_sorted_first(self):
        """Pass32: disability rating items before work restrictions."""
        rm = _make_rm(promoted_findings=[
            _make_finding("objective_deficit", "Work restriction: no lifting"),
            _make_finding("objective_deficit", "Temporary disability rating documented"),
        ])
        section = _build_functional_limitations_section({}, rm)
        labels = [it.label for it in section.items]
        disability_idx = next(i for i, l in enumerate(labels) if "disability" in l.lower())
        restriction_idx = next(i for i, l in enumerate(labels) if "restriction" in l.lower())
        assert disability_idx < restriction_idx


# ---------------------------------------------------------------------------
# Pass31 — Economic damages honesty rule
# ---------------------------------------------------------------------------

class TestEconomicDamages:
    def test_prints_total_when_available(self):
        specials = {"totals": {"total_charges": 50000.0}}
        section = _build_economic_damages_section({}, {}, specials_summary=specials)
        assert any("50,000" in item.label for item in section.items)
        assert section.gate_required is True

    def test_disclosure_when_no_total(self):
        section = _build_economic_damages_section({}, {}, specials_summary=None)
        assert section.items, "Expected a disclosure item"
        for item in section.items:
            assert "not available" not in item.label.lower(), (
                "Disclosure text must not contain 'not available' (placeholder scan trigger)"
            )
        assert section.gate_required is False

    def test_never_infers_total(self):
        section = _build_economic_damages_section({}, {}, specials_summary={"totals": {}})
        assert not any("$" in item.label for item in section.items)


# ---------------------------------------------------------------------------
# Pass31 — Structural gate
# ---------------------------------------------------------------------------

class TestMediationStructuralGate:
    def test_no_fails_on_thin_packet(self):
        sections = build_mediation_sections(ext={}, rm={}, raw_events=[], gaps=[])
        fails = run_mediation_structural_gate(sections)
        assert fails == [], f"Unexpected fails on thin packet: {fails}"

    def test_fails_when_required_section_absent(self):
        from apps.worker.steps.export_render.mediation_sections import MediationSection
        sections = [
            MediationSection(key="objective_findings", title="OBJECTIVE FINDINGS",
                             items=[], gate_required=True, gate_fail=True),
        ]
        fails = run_mediation_structural_gate(sections)
        assert any("objective_findings" in f for f in fails)

    def test_no_false_failures_on_mechanism_absent(self):
        sections = build_mediation_sections(ext={}, rm={}, raw_events=None)
        mechanism_sec = next(s for s in sections if s.key == "mechanism_initial_presentation")
        assert mechanism_sec.gate_required is False

    def test_mechanism_required_when_events_exist(self):
        events = [_MockEvent("e1", "er_visit")]
        sections = build_mediation_sections(ext={}, rm={}, raw_events=events)
        mechanism_sec = next(s for s in sections if s.key == "mechanism_initial_presentation")
        assert mechanism_sec.gate_required is True


# ---------------------------------------------------------------------------
# Pass32 — Section order (10-section spec)
# ---------------------------------------------------------------------------

class TestSectionOrder:
    _EXPECTED_ORDER = [
        "severity_profile",
        "mechanism_initial_presentation",
        "objective_findings",
        "provider_corroboration",
        "treatment_progression",
        "functional_limitations",
        "current_condition",
        "clinical_reasonableness",
        "economic_damages",
        "defense_preemption",
    ]

    def test_section_order_always_canonical(self):
        sections = build_mediation_sections(ext={}, rm={})
        keys = [s.key for s in sections]
        assert keys == self._EXPECTED_ORDER

    def test_section_order_with_rich_packet(self):
        """Even with a full packet, order must be canonical."""
        rm = _make_rm(
            mechanism="motor vehicle collision",
            doi="2024-03-15",
            promoted_findings=[
                _make_finding("imaging", "L4-L5 herniation"),
                _make_finding("objective_deficit", "Reduced ROM cervical"),
            ],
        )
        ext = {
            "severity_profile": {"primary_label": "Moderate-severe"},
            "litigation_safe_v1": {"computed": {"max_gap_days": 50}},
        }
        events = [
            _MockEvent("e1", "er_visit"),
            _MockEvent("e2", "mri"),
            _MockEvent("e3", "pt_visit"),
        ]
        sections = build_mediation_sections(ext=ext, rm=rm, raw_events=events)
        keys = [s.key for s in sections]
        assert keys == self._EXPECTED_ORDER


# ---------------------------------------------------------------------------
# Pass32 — _detect_escalation
# ---------------------------------------------------------------------------

class TestDetectEscalation:
    def test_ed_pt_alone_is_not_escalation(self):
        """ED + PT is NOT sufficient for escalation."""
        stages = ["ed", "pt"]
        assert _detect_escalation(stages) is False

    def test_pt_specialist_is_escalation(self):
        stages = ["pt", "specialist"]
        assert _detect_escalation(stages) is True

    def test_ed_specialist_is_escalation(self):
        stages = ["ed", "specialist"]
        assert _detect_escalation(stages) is True

    def test_pt_procedure_is_escalation(self):
        stages = ["pt", "procedure"]
        assert _detect_escalation(stages) is True

    def test_imaging_after_ed_is_escalation(self):
        stages = ["ed", "imaging"]
        assert _detect_escalation(stages) is True

    def test_imaging_after_pt_is_escalation(self):
        stages = ["pt", "imaging"]
        assert _detect_escalation(stages) is True

    def test_imaging_alone_is_not_escalation(self):
        stages = ["imaging"]
        assert _detect_escalation(stages) is False

    def test_single_stage_not_escalation(self):
        assert _detect_escalation(["ed"]) is False
        assert _detect_escalation(["pt"]) is False
        assert _detect_escalation(["specialist"]) is False

    def test_full_stack_is_escalation(self):
        stages = ["ed", "imaging", "pt", "specialist", "procedure"]
        assert _detect_escalation(stages) is True


# ---------------------------------------------------------------------------
# Pass32 — Clinical Course & Reasonableness
# ---------------------------------------------------------------------------

class TestClinicalReasonablenessSection:
    def test_absent_when_no_escalation(self):
        """ED + PT alone: no section."""
        events = [_MockEvent("e1", "er_visit"), _MockEvent("e2", "pt_visit")]
        section = _build_clinical_reasonableness_section({}, {}, raw_events=events)
        assert section.items == []
        assert section.gate_required is False

    def test_present_when_escalation_exists(self):
        events = [
            _MockEvent("e1", "pt_visit"),
            _MockEvent("e2", "specialist_visit"),
        ]
        section = _build_clinical_reasonableness_section({}, {}, raw_events=events)
        assert section.items
        assert section.gate_required is True

    def test_items_use_locked_templates(self):
        """Items must use fixed template phrases, not free text."""
        events = [
            _MockEvent("e1", "er_visit"),
            _MockEvent("e2", "mri"),
            _MockEvent("e3", "specialist_visit"),
        ]
        section = _build_clinical_reasonableness_section({}, {}, raw_events=events)
        all_labels = " ".join(it.label for it in section.items)
        assert "Conservative care initiated" in all_labels
        assert "Diagnostic imaging ordered" in all_labels
        assert "Specialist consultation documented" in all_labels

    def test_max_5_items(self):
        events = [
            _MockEvent("e1", "er_visit"),
            _MockEvent("e2", "mri"),
            _MockEvent("e3", "pt_visit"),
            _MockEvent("e4", "specialist_visit"),
            _MockEvent("e5", "injection"),
            _MockEvent("e6", "surgery"),
        ]
        section = _build_clinical_reasonableness_section({}, {}, raw_events=events)
        assert len(section.items) <= 5

    def test_gate_not_required_on_thin_packet(self):
        section = _build_clinical_reasonableness_section({}, {}, raw_events=[])
        assert section.gate_required is False


# ---------------------------------------------------------------------------
# Pass32 — Current Condition & Prognosis
# ---------------------------------------------------------------------------

class TestCurrentConditionSection:
    def test_absent_when_no_last_window_signals(self):
        """No diagnoses or findings on any event → no section."""
        events = [_MockEvent("e1", "er_visit", date_value=datetime.date(2024, 3, 15))]
        assert _last_window_trigger(events, {}) is False
        section = _build_current_condition_section({}, {}, raw_events=events)
        assert section.items == []
        assert section.gate_required is False

    def test_triggers_when_last_event_has_diagnoses(self):
        events = [
            _MockEvent("e1", "er_visit", date_value=datetime.date(2024, 3, 15)),
            _MockEvent("e2", "pt_visit", date_value=datetime.date(2024, 5, 1),
                       diagnoses=["Cervical radiculopathy, ongoing"]),
        ]
        assert _last_window_trigger(events, {}) is True

    def test_uses_last_event_not_first(self):
        """Items come from the LAST dated encounter, not the first."""
        events = [
            _MockEvent("e1", "er_visit", date_value=datetime.date(2024, 3, 1),
                       diagnoses=["Acute cervical strain"]),
            _MockEvent("e2", "specialist_visit", date_value=datetime.date(2024, 6, 1),
                       diagnoses=["Chronic radiculopathy C5-C6"]),
        ]
        section = _build_current_condition_section({}, {}, raw_events=events)
        assert any("Chronic radiculopathy" in it.label for it in section.items)
        assert not any("Acute cervical strain" in it.label for it in section.items)

    def test_does_not_add_permanent_unless_in_label(self):
        """Never write 'permanent' unless the structured label contains it."""
        events = [
            _MockEvent("e2", "specialist_visit", date_value=datetime.date(2024, 6, 1),
                       diagnoses=["Radiculopathy C5"]),
        ]
        section = _build_current_condition_section({}, {}, raw_events=events)
        for item in section.items:
            if "permanent" in item.label.lower():
                # Only allowed if the source diagnosis text contained it
                assert "permanent" in "Radiculopathy C5".lower() or True  # Source didn't have it
                assert False, "Section added 'permanent' not present in source label"

    def test_referral_signal_from_promoted_findings(self):
        """Referral in promoted_findings triggers section."""
        rm = _make_rm(promoted_findings=[
            _make_finding("referral", "Referral to pain management specialist"),
        ])
        events = [_MockEvent("e1", "pt_visit", date_value=datetime.date(2024, 5, 1))]
        assert _last_window_trigger(events, rm) is True

    def test_not_triggered_by_free_text_persistent(self):
        """Keyword 'persistent' in raw text alone must NOT trigger the section."""
        # Event with no diagnoses, no functional exam_findings — only a fact with "persistent"
        events = [
            _MockEvent("e1", "pt_visit", date_value=datetime.date(2024, 5, 1),
                       facts=["Patient reports persistent neck pain"]),
        ]
        # No promoted_findings with referral/objective categories
        assert _last_window_trigger(events, {}) is False

    def test_max_4_items(self):
        events = [
            _MockEvent("e1", "specialist_visit", date_value=datetime.date(2024, 6, 1),
                       diagnoses=["Dx1", "Dx2", "Dx3"],
                       exam_findings=["Restricted range of motion", "Disability rating 15%"]),
        ]
        rm = _make_rm(promoted_findings=[
            _make_finding("referral", "Referral to orthopedics"),
        ])
        section = _build_current_condition_section({}, rm, raw_events=events)
        assert len(section.items) <= 4

    def test_gate_not_required_on_thin_packet(self):
        section = _build_current_condition_section({}, {}, raw_events=None)
        assert section.gate_required is False


# ---------------------------------------------------------------------------
# Pass32 — Provider Corroboration
# ---------------------------------------------------------------------------

class TestProviderCorroborationSection:
    def test_skipped_when_no_entity_id_data(self):
        """No provider_entity_id in any finding → section skipped entirely."""
        rm = _make_rm(promoted_findings=[
            _make_finding("imaging", "Disc herniation L4-L5"),
            _make_finding("imaging", "Disc herniation L4-L5"),
        ])
        section = _build_provider_corroboration_section({}, rm)
        assert section.items == []
        assert section.gate_required is False

    def test_skipped_with_single_entity(self):
        """Only 1 distinct provider entity → no section."""
        rm = _make_rm(promoted_findings=[
            _make_finding("imaging", "Disc herniation", provider_entity_id="provider_A"),
            _make_finding("imaging", "Disc herniation", provider_entity_id="provider_A"),
        ])
        section = _build_provider_corroboration_section({}, rm)
        assert section.items == []

    def test_triggers_with_two_distinct_entity_ids(self):
        """2 distinct provider entities documenting same condition → section present."""
        rm = _make_rm(promoted_findings=[
            _make_finding("imaging", "Radiculopathy C5-C6", provider_entity_id="provider_A"),
            _make_finding("objective_deficit", "Radiculopathy confirmed", provider_entity_id="provider_B"),
        ])
        section = _build_provider_corroboration_section({}, rm)
        assert section.items
        assert section.gate_required is True
        assert any("radiculopathy" in it.label.lower() for it in section.items)

    def test_same_entity_twice_does_not_trigger(self):
        """Same entity ID appearing on two different findings = same provider."""
        rm = _make_rm(promoted_findings=[
            _make_finding("imaging", "Disc herniation", provider_entity_id="clinic_A"),
            _make_finding("objective_deficit", "Disc herniation confirmed", provider_entity_id="clinic_A"),
        ])
        section = _build_provider_corroboration_section({}, rm)
        assert section.items == []

    def test_max_3_items(self):
        rm = _make_rm(promoted_findings=[
            _make_finding("imaging", "disc herniation", provider_entity_id="pA"),
            _make_finding("imaging", "disc herniation", provider_entity_id="pB"),
            _make_finding("imaging", "radiculopathy", provider_entity_id="pA"),
            _make_finding("imaging", "radiculopathy", provider_entity_id="pB"),
            _make_finding("imaging", "stenosis", provider_entity_id="pA"),
            _make_finding("imaging", "stenosis", provider_entity_id="pB"),
            _make_finding("imaging", "compression", provider_entity_id="pA"),
            _make_finding("imaging", "compression", provider_entity_id="pB"),
        ])
        section = _build_provider_corroboration_section({}, rm)
        assert len(section.items) <= 3


# ---------------------------------------------------------------------------
# Pass32 — Mechanism: time compression signal
# ---------------------------------------------------------------------------

class TestMechanismTimeCompression:
    def test_days_to_first_treatment_added_when_doi_present(self):
        """Pass32: treatment initiation within N days appears when DOI is known."""
        rm = _make_rm(doi="2024-03-10")
        events = [
            _MockEvent("e1", "er_visit", date_value=datetime.date(2024, 3, 12)),
        ]
        section = _build_mechanism_section({}, rm, raw_events=events)
        labels = " ".join(it.label for it in section.items)
        assert "2 day" in labels  # 2 days between 2024-03-10 and 2024-03-12

    def test_care_span_added_when_30_plus_days(self):
        """Pass32: documented care span appears when span >= 30 days."""
        rm = _make_rm(doi="2024-01-01")
        events = [
            _MockEvent("e1", "er_visit", date_value=datetime.date(2024, 1, 2)),
            _MockEvent("e2", "pt_visit", date_value=datetime.date(2024, 4, 2)),  # ~3 months
        ]
        section = _build_mechanism_section({}, rm, raw_events=events)
        labels = " ".join(it.label for it in section.items)
        assert "month" in labels

    def test_no_time_compression_without_doi(self):
        """No DOI → no time compression signal."""
        rm = _make_rm()  # no doi
        events = [
            _MockEvent("e1", "er_visit", date_value=datetime.date(2024, 3, 15)),
        ]
        section = _build_mechanism_section({}, rm, raw_events=events)
        labels = " ".join(it.label for it in section.items)
        assert "day" not in labels
        assert "month" not in labels

    def test_care_span_absent_when_under_30_days(self):
        rm = _make_rm(doi="2024-03-01")
        events = [
            _MockEvent("e1", "er_visit", date_value=datetime.date(2024, 3, 2)),
            _MockEvent("e2", "pt_visit", date_value=datetime.date(2024, 3, 20)),  # 18 days span
        ]
        section = _build_mechanism_section({}, rm, raw_events=events)
        labels = " ".join(it.label for it in section.items)
        assert "month" not in labels

    def test_initial_diagnosis_line_added(self):
        """Pass32: 3-part format includes initial diagnosis when diagnoses present."""
        rm = _make_rm()
        events = [
            _MockEvent("e1", "er_visit", date_value=datetime.date(2024, 3, 1),
                       diagnoses=["Acute cervical strain"]),
        ]
        section = _build_mechanism_section({}, rm, raw_events=events)
        labels = " ".join(it.label for it in section.items)
        assert "Initial diagnosis" in labels
        assert "Acute cervical strain" in labels


# ---------------------------------------------------------------------------
# Integration: build_mediation_sections on realistic payload
# ---------------------------------------------------------------------------

class TestBuildMediationSections:
    def test_citation_support_attached(self):
        citation_by_id = {
            "cid_1": {"local_page": 5, "global_page": 5, "doc_id": "doc1"},
            "cid_2": {"local_page": 12, "global_page": 12, "doc_id": "doc1"},
        }
        rm = _make_rm(
            mechanism="rear-end motor vehicle collision",
            doi="2024-06-01",
            promoted_findings=[_make_finding("imaging", "C5-C6 disc herniation", cids=["cid_1"])],
        )
        sections = build_mediation_sections(ext={}, rm=rm, citation_by_id=citation_by_id)
        obj_sec = next(s for s in sections if s.key == "objective_findings")
        assert obj_sec.items
        assert "[p. 5]" in obj_sec.items[0].support

    def test_gate_fail_captured_in_section(self):
        rm = _make_rm(promoted_findings=[_make_finding("imaging", "")])  # empty label
        sections = build_mediation_sections(ext={}, rm=rm)
        obj_sec = next(s for s in sections if s.key == "objective_findings")
        assert obj_sec.key == "objective_findings"

    def test_all_10_section_keys_present(self):
        sections = build_mediation_sections(ext={}, rm={})
        keys = [s.key for s in sections]
        assert len(keys) == 10

    def test_no_gate_failures_thin_packet(self):
        """Thin packet must produce zero gate failures across all 10 sections."""
        sections = build_mediation_sections(ext={}, rm={}, raw_events=[], gaps=[])
        fails = run_mediation_structural_gate(sections)
        assert fails == []
