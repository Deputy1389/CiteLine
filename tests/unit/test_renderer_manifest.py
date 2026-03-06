from datetime import date

from apps.worker.steps.step_renderer_manifest import build_renderer_manifest
from packages.shared.models import (
    BBox,
    Citation,
    DateKind,
    DateSource,
    Event,
    EventDate,
    EventType,
    Fact,
    FactKind,
)


def _pt_event(event_id: str, start: date, end: date, fact_text: str, citation_ids: list[str] | None = None) -> Event:
    return Event(
        event_id=event_id,
        provider_id="prov-pt",
        event_type=EventType.PT_VISIT,
        date=EventDate(kind=DateKind.RANGE, value={"start": start, "end": end}, source=DateSource.TIER1),
        facts=[Fact(text=fact_text, kind=FactKind.OTHER, verbatim=True, citation_ids=citation_ids or [])],
        confidence=85,
        citation_ids=citation_ids or [],
        source_page_numbers=[52],
    )


def test_renderer_manifest_prefers_aggregate_pt_count_and_sanitizes_dates() -> None:
    events = [
        _pt_event("pt-1", date(1900, 1, 1), date(1900, 1, 1), "PT sessions documented: 117", ["c1"]),
        _pt_event("pt-2", date(2024, 10, 17), date(2025, 11, 13), "Aggregated PT sessions (117 encounters)", ["c2"]),
    ]
    manifest = build_renderer_manifest(events=events, evidence_graph_extensions={}, specials_summary=None)
    assert manifest.pt_summary.total_encounters == 117
    assert manifest.pt_summary.count_source == "aggregate_snippet"
    assert manifest.pt_summary.date_start == "2024-10-17"
    assert manifest.pt_summary.date_end == "2025-11-13"


def test_renderer_manifest_pt_conflict_adds_reconciliation_note() -> None:
    events = [
        _pt_event("pt-1", date(2024, 10, 17), date(2025, 11, 13), "PT sessions documented: 117", ["c1"]),
        _pt_event("pt-2", date(2024, 10, 20), date(2025, 11, 13), "Aggregated PT sessions (141 encounters)", ["c2"]),
    ]
    manifest = build_renderer_manifest(events=events, evidence_graph_extensions={}, specials_summary=None)
    assert manifest.pt_summary.total_encounters == 141
    assert manifest.pt_summary.encounter_count_min == 117
    assert manifest.pt_summary.encounter_count_max == 141
    assert manifest.pt_summary.reconciliation_note
    note = manifest.pt_summary.reconciliation_note or ""
    assert ("Chronology verifies" in note) or ("Dated PT encounters documented in this packet" in note)


def test_renderer_manifest_promotes_claim_rows_with_priority_categories() -> None:
    claim_rows = [
        {
            "event_id": "e1",
            "claim_type": "INJURY_DX",
            "assertion": "Cervical disc displacement with radiculopathy",
            "citations": ["packet.pdf p. 101"],
            "selection_score": 90,
        },
        {
            "event_id": "e2",
            "claim_type": "IMAGING_FINDING",
            "assertion": "Unremarkable lumbar spine series",
            "citations": ["packet.pdf p. 88"],
            "selection_score": 92,
            "flags": ["degenerative_language"],
        },
        {
            "event_id": "e3",
            "claim_type": "PROCEDURE",
            "assertion": "Cervical epidural steroid injection performed",
            "citations": ["packet.pdf p. 140"],
            "selection_score": 85,
        },
        {
            "event_id": "e4",
            "claim_type": "SYMPTOM",
            "assertion": "Weakness 4/5 documented",
            "citations": ["packet.pdf p. 100"],
            "selection_score": 80,
        },
    ]
    manifest = build_renderer_manifest(
        events=[],
        evidence_graph_extensions={"claim_rows": claim_rows},
        specials_summary={"flags": ["PARTIAL_BILLING_ONLY"], "by_provider": [{"provider_display_name": "PT", "charges": 100}]},
    )
    categories = [f.category for f in manifest.promoted_findings]
    assert "objective_deficit" in categories
    assert "diagnosis" in categories
    assert "procedure" in categories
    low_img = next(f for f in manifest.promoted_findings if "Unremarkable lumbar spine series" in f.label)
    assert low_img.headline_eligible is False
    assert low_img.finding_polarity == "negative"
    assert manifest.billing_completeness == "partial"
    assert manifest.top_case_drivers


def test_renderer_manifest_extracts_mechanism_from_cited_event_text() -> None:
    evt = Event(
        event_id="er-1",
        provider_id="prov-er",
        event_type=EventType.ER_VISIT,
        reason_for_visit="Rear-end MVC with neck and back pain",
        facts=[Fact(text="Patient presents after rear-end motor vehicle collision", kind=FactKind.OTHER, verbatim=True, citation_ids=["c-mvc"])],
        confidence=90,
        citation_ids=["c-mvc"],
    )
    manifest = build_renderer_manifest(events=[evt], evidence_graph_extensions={}, specials_summary=None)
    assert manifest.mechanism.value == "rear-end motor vehicle collision"
    assert "c-mvc" in manifest.mechanism.citation_ids


def test_renderer_manifest_mechanism_prefers_ed_hpi_like_citation_context() -> None:
    citations = [
        Citation(
            citation_id="c-ortho",
            source_document_id="doc-1",
            page_number=104,
            snippet="Orthopedic consult note: motor vehicle accident with persistent neck pain.",
            bbox=BBox(x=1, y=1, w=1, h=1),
        ),
        Citation(
            citation_id="c-ed",
            source_document_id="doc-1",
            page_number=11,
            snippet="ED HPI: rear-end MVA. Chief complaint neck pain after collision.",
            bbox=BBox(x=1, y=1, w=1, h=1),
        ),
    ]
    evt = Event(
        event_id="er-ctx-1",
        provider_id="prov-er",
        event_type=EventType.ER_VISIT,
        reason_for_visit="Motor vehicle collision with neck pain",
        facts=[Fact(text="Presented to ED after rear-end MVC.", kind=FactKind.OTHER, verbatim=True, citation_ids=["c-ortho", "c-ed"])],
        confidence=90,
        citation_ids=["c-ortho", "c-ed"],
        source_page_numbers=[11, 104],
    )
    ext: dict = {}
    manifest = build_renderer_manifest(events=[evt], evidence_graph_extensions=ext, specials_summary=None, citations=citations)
    assert manifest.mechanism.value == "rear-end motor vehicle collision"
    assert manifest.mechanism.citation_ids
    assert manifest.mechanism.citation_ids[0] == "c-ed"
    audit = ext.get("mechanism_selection_audit") or {}
    assert audit.get("selected_candidate", {}).get("citation_id") == "c-ed"


def test_renderer_manifest_falls_back_to_citation_snippets_for_mechanism_dx_and_pt_count() -> None:
    citations = [
        Citation(citation_id="c1", source_document_id="doc-1", page_number=11, snippet="Rear-end motor vehicle collision", bbox=BBox(x=1, y=1, w=1, h=1)),
        Citation(citation_id="c2", source_document_id="doc-1", page_number=23, snippet="Aggregated PT sessions (141 encounters) (ROM, Exercise, Gait, Strength).", bbox=BBox(x=1, y=1, w=1, h=1)),
        Citation(citation_id="c3", source_document_id="doc-1", page_number=112, snippet="1. Cervical Disc Displacement (ICD-10 M50.20) with Radiculopathy (M54.12)", bbox=BBox(x=1, y=1, w=1, h=1)),
        Citation(citation_id="c4", source_document_id="doc-1", page_number=108, snippet="The MRI shows significant disc material extending into the neural foramen on the left side at the C5-C6 level.", bbox=BBox(x=1, y=1, w=1, h=1)),
    ]
    # One PT event with low aggregate in event facts to ensure citation fallback can elevate max.
    events = [_pt_event("pt-1", date(2024, 10, 17), date(2025, 11, 13), "PT sessions documented: 117", ["ept1"])]
    manifest = build_renderer_manifest(events=events, evidence_graph_extensions={}, specials_summary=None, citations=citations)
    assert manifest.mechanism.value == "rear-end motor vehicle collision"
    assert manifest.pt_summary.total_encounters == 141
    cats = [f.category for f in manifest.promoted_findings]
    assert "diagnosis" in cats
    assert "imaging" in cats
    assert any(f.category == "visit_count" and "141 encounters" in f.label for f in manifest.promoted_findings)
    assert not any(f.category == "objective_deficit" and "141 encounters" in f.label for f in manifest.promoted_findings)


def test_renderer_manifest_mechanism_citation_fallback_prefers_non_negated_rear_end() -> None:
    citations = [
        Citation(
            citation_id="c-neg",
            source_document_id="doc-1",
            page_number=4,
            snippet="ED triage: patient denies MVC today.",
            bbox=BBox(x=1, y=1, w=1, h=1),
        ),
        Citation(
            citation_id="c-pos",
            source_document_id="doc-1",
            page_number=5,
            snippet="ED HPI: neck and back pain following MVC rear-end MVA earlier today.",
            bbox=BBox(x=1, y=1, w=1, h=1),
        ),
    ]
    manifest = build_renderer_manifest(events=[], evidence_graph_extensions={}, specials_summary=None, citations=citations)
    assert manifest.mechanism.value == "rear-end motor vehicle collision"
    assert manifest.mechanism.citation_ids == ["c-pos"]


def test_renderer_manifest_mechanism_citation_fallback_respects_negation_only() -> None:
    citations = [
        Citation(
            citation_id="c-neg-only",
            source_document_id="doc-1",
            page_number=3,
            snippet="Chief complaint: patient denies motor vehicle collision.",
            bbox=BBox(x=1, y=1, w=1, h=1),
        )
    ]
    manifest = build_renderer_manifest(events=[], evidence_graph_extensions={}, specials_summary=None, citations=citations)
    assert manifest.mechanism.value is None
    assert manifest.mechanism.citation_ids == []


def test_negative_and_junk_imaging_are_not_headline_promoted() -> None:
    citations = [
        Citation(citation_id="c1", source_document_id="doc-1", page_number=39, snippet="No fracture or dislocation.", bbox=BBox(x=1, y=1, w=1, h=1)),
        Citation(citation_id="c2", source_document_id="doc-1", page_number=39, snippet="Fax ID: 975207 | 10/20/2024 16:22 | Page 2", bbox=BBox(x=1, y=1, w=1, h=1)),
        Citation(citation_id="c3", source_document_id="doc-1", page_number=108, snippet="The MRI shows significant disc material extending into the neural foramen on the left side at the C5-C6 level.", bbox=BBox(x=1, y=1, w=1, h=1)),
    ]
    manifest = build_renderer_manifest(events=[], evidence_graph_extensions={}, specials_summary=None, citations=citations)
    found_pathology = next(f for f in manifest.promoted_findings if "neural foramen" in f.label)
    assert found_pathology.category == "imaging"
    assert found_pathology.headline_eligible is True
    assert found_pathology.finding_polarity == "positive"
    neg = [f for f in manifest.promoted_findings if "No fracture or dislocation." in f.label]
    assert neg and all(f.headline_eligible is False for f in neg)
    assert not any("Fax ID" in f.label for f in manifest.promoted_findings)


def test_imaging_snippet_trims_trailing_fragment_and_mri_leadin() -> None:
    citations = [
        Citation(
            citation_id="c1",
            source_document_id="doc-1",
            page_number=108,
            snippet="The MRI shows significant disc material extending into the neural foramen on the left side at the C5-C6 level. This directly",
            bbox=BBox(x=1, y=1, w=1, h=1),
        )
    ]
    manifest = build_renderer_manifest(events=[], evidence_graph_extensions={}, specials_summary=None, citations=citations)
    img = next(f for f in manifest.promoted_findings if f.category == "imaging")
    assert "This directly" not in img.label
    assert not img.label.lower().startswith("the mri shows ")


def test_normal_lordotic_curvature_not_promoted_as_objective_headline() -> None:
    citations = [
        Citation(
            citation_id="c1",
            source_document_id="doc-1",
            page_number=109,
            snippet="normal lordotic curvature, which is a common finding in the setting of acute or subacute muscle spasm",
            bbox=BBox(x=1, y=1, w=1, h=1),
        )
    ]
    manifest = build_renderer_manifest(events=[], evidence_graph_extensions={}, specials_summary=None, citations=citations)
    assert not any(f.category == "objective_deficit" and "normal lordotic curvature" in f.label.lower() for f in manifest.promoted_findings)


def test_diagnosis_label_cleanup_strips_assessment_prefixes() -> None:
    citations = [
        Citation(
            citation_id="c1",
            source_document_id="doc-1",
            page_number=112,
            snippet="ASSESSMENT AND TREATMENT PLAN 1. Cervical Disc Displacement (ICD-10 M50.20) with Radiculopathy (M54.12)",
            bbox=BBox(x=1, y=1, w=1, h=1),
        )
    ]
    manifest = build_renderer_manifest(events=[], evidence_graph_extensions={}, specials_summary=None, citations=citations)
    dx = next(f for f in manifest.promoted_findings if f.category == "diagnosis")
    assert not dx.label.upper().startswith("ASSESSMENT AND TREATMENT PLAN")
    assert dx.label.startswith("Cervical Disc Displacement")


def test_renderer_manifest_consolidates_lordosis_spasm_duplicates_but_keeps_structural_pathology() -> None:
    claim_rows = [
        {
            "event_id": "e1",
            "claim_type": "IMAGING_FINDING",
            "assertion": "Loss of normal cervical lordosis consistent with muscle spasm",
            "citations": ["packet.pdf p. 10"],
            "selection_score": 70,
            "body_region": "cervical",
        },
        {
            "event_id": "e2",
            "claim_type": "IMAGING_FINDING",
            "assertion": "Straightening of cervical lordosis suggesting spasm",
            "citations": ["packet.pdf p. 11"],
            "selection_score": 68,
            "body_region": "cervical",
        },
        {
            "event_id": "e3",
            "claim_type": "IMAGING_FINDING",
            "assertion": "C5-C6 disc protrusion with left foraminal narrowing",
            "citations": ["packet.pdf p. 12"],
            "selection_score": 92,
            "body_region": "cervical",
        },
    ]
    manifest = build_renderer_manifest(events=[], evidence_graph_extensions={"claim_rows": claim_rows}, specials_summary=None)
    labels = [f.label.lower() for f in manifest.promoted_findings if f.category == "imaging"]
    assert any("disc protrusion" in l for l in labels)
    lordosis_variants = [f for f in manifest.promoted_findings if f.category in {"imaging", "objective_deficit"} and ("lordosis" in f.label.lower() or "spasm" in f.label.lower())]
    assert len(lordosis_variants) == 1
    assert lordosis_variants[0].semantic_family
    assert lordosis_variants[0].finding_source_count == 2
    assert "imaging" in (lordosis_variants[0].source_families or [])


def test_renderer_manifest_suppresses_generic_synthetic_and_admin_claim_rows() -> None:
    claim_rows = [
        {
            "event_id": "e1",
            "claim_type": "INJURY_DX",
            "assertion": "PRIMARY DIAGNOSIS: Medical Condition B20",
            "citations": ["packet.pdf p. 1"],
            "selection_score": 4,
            "support_score": 2,
        },
        {
            "event_id": "e2",
            "claim_type": "TREATMENT_VISIT",
            "assertion": "ADMISSION RECORD: #22380825",
            "citations": ["packet.pdf p. 1"],
            "selection_score": 4,
            "support_score": 0,
        },
        {
            "event_id": "e3",
            "claim_type": "TREATMENT_VISIT",
            "assertion": "ADMITTED: 2200-06-05 05:43:00 | DISCHARGED: 2200-06-05 10:26:00",
            "citations": ["packet.pdf p. 4"],
            "selection_score": 4,
            "support_score": 0,
        },
        {
            "event_id": "e4",
            "claim_type": "INJURY_DX",
            "assertion": "C5-C6 disc protrusion with left foraminal narrowing",
            "citations": ["packet.pdf p. 12"],
            "selection_score": 92,
            "support_score": 3,
            "body_region": "cervical",
        },
    ]
    manifest = build_renderer_manifest(events=[], evidence_graph_extensions={"claim_rows": claim_rows}, specials_summary=None)
    labels = [f.label for f in manifest.promoted_findings]
    assert "PRIMARY DIAGNOSIS: Medical Condition B20" not in labels
    assert "ADMISSION RECORD: #22380825" not in labels
    assert "ADMITTED: 2200-06-05 05:43:00 | DISCHARGED: 2200-06-05 10:26:00" not in labels
    assert any("disc protrusion" in label.lower() for label in labels)


def test_renderer_manifest_preserves_substantive_treatment_rows_when_clinically_meaningful() -> None:
    claim_rows = [
        {
            "event_id": "e1",
            "claim_type": "TREATMENT_VISIT",
            "assertion": "Follow-up orthopedic consult recommended due to persistent weakness and pain.",
            "citations": ["packet.pdf p. 5"],
            "selection_score": 35,
            "support_score": 2,
        }
    ]
    manifest = build_renderer_manifest(events=[], evidence_graph_extensions={"claim_rows": claim_rows}, specials_summary=None)
    assert len(manifest.promoted_findings) == 1
    assert manifest.promoted_findings[0].category in {"treatment", "objective_deficit"}
    assert "orthopedic consult" in manifest.promoted_findings[0].label.lower()
