from datetime import datetime, timezone
from datetime import date

import io
from pypdf import PdfReader

from apps.worker.project.models import ChronologyProjection, ChronologyProjectionEntry
from apps.worker.steps.export_render.timeline_pdf import generate_pdf_from_projection
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


def _pdf_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join([p.extract_text() or "" for p in reader.pages])


def test_pdf_order_and_snapshot_layout() -> None:
    projection = ChronologyProjection(
        generated_at=datetime.now(timezone.utc),
        entries=[
            ChronologyProjectionEntry(
                event_id="evt1",
                date_display="2024-01-01",
                event_type_display="Imaging Study",
                provider_display="Provider A",
                facts=["Very partner example rate remain better letter vehicle just."],
                citation_display="records.pdf p. 2",
            ),
        ],
    )
    pdf_bytes = generate_pdf_from_projection(
        matter_title="Test Matter",
        projection=projection,
        gaps=[],
        narrative_synthesis="Very partner example rate remain better letter vehicle just.",
        appendix_entries=projection.entries,
        raw_events=None,
        all_citations=[],
        page_map=None,
        missing_records_payload=None,
        evidence_graph_payload={},
        run_id=None,
    )
    full_text = _pdf_text(pdf_bytes)
    assert "CASE SNAPSHOT (30-SECOND READ)" in full_text
    assert "Medical Timeline (Litigation Ready)" in full_text
    assert "Imaging & Objective Findings" in full_text
    assert "Treatment Course & Compliance" in full_text
    assert "Billing / Specials" in full_text
    assert "Citation Index & Record Appendix" in full_text
    assert full_text.find("CASE SNAPSHOT (30-SECOND READ)") < full_text.find("Medical Timeline (Litigation Ready)")
    assert full_text.find("Medical Timeline (Litigation Ready)") < full_text.find("Imaging & Objective Findings")
    assert full_text.find("Imaging & Objective Findings") < full_text.find("Treatment Course & Compliance")


def test_guardrail_bans_undermining_phrase_when_disc_dx_present() -> None:
    projection = ChronologyProjection(
        generated_at=datetime.now(timezone.utc),
        entries=[
            ChronologyProjectionEntry(
                event_id="evt-disc",
                date_display="2024-11-18",
                event_type_display="Imaging Study",
                provider_display="Radiology",
                facts=["Cervical MRI shows disc material extending into neural foramen at C5-C6"],
                citation_display="records.pdf p. 10",
                confidence=95,
            ),
        ],
    )
    evidence_graph_payload = {
        "extensions": {
            "claim_rows": [
                {
                    "event_id": "evt-disc",
                    "claim_type": "INJURY_DX",
                    "date": "2024-11-18",
                    "assertion": "Cervical disc displacement with radiculopathy",
                    "citations": ["p. 10"],
                    "selection_score": 90,
                }
            ]
        }
    }
    pdf_bytes = generate_pdf_from_projection(
        matter_title="Guardrail Case",
        projection=projection,
        gaps=[],
        narrative_synthesis="No specific traumatic injuries isolated.",
        appendix_entries=projection.entries,
        raw_events=[],
        all_citations=[],
        page_map=None,
        missing_records_payload=None,
        evidence_graph_payload=evidence_graph_payload,
        run_id=None,
    )
    text = _pdf_text(pdf_bytes).lower()
    assert "no specific traumatic injuries isolated" not in text
    assert "radiculopathy" in text or "disc displacement" in text


def test_pt_encounter_count_is_shown_when_extracted() -> None:
    projection = ChronologyProjection(
        generated_at=datetime.now(timezone.utc),
        entries=[
            ChronologyProjectionEntry(
                event_id="evt-pt",
                date_display="2024-10-17 to 2025-11-13",
                event_type_display="Physical Therapy Visit",
                provider_display="Elite Physical Therapy",
                facts=["PT sessions documented: 117"],
                citation_display="records.pdf p. 52",
                confidence=90,
            ),
        ],
    )
    raw_events = [
        Event(
            event_id="evt-pt",
            provider_id="prov-1",
            event_type=EventType.PT_VISIT,
            date=EventDate(kind=DateKind.RANGE, value={"start": date(2024, 10, 17), "end": date(2025, 11, 13)}, source=DateSource.TIER1),  # pydantic coerces dict to DateRange
            facts=[Fact(text="PT sessions documented: 117", kind=FactKind.OTHER, verbatim=True, citation_ids=["cit-pt"])],
            confidence=85,
            citation_ids=["cit-pt"],
            source_page_numbers=[52],
        )
    ]
    citations = [Citation(citation_id="cit-pt", source_document_id="doc-1", page_number=52, snippet="PT sessions documented: 117", bbox=BBox(x=1, y=1, w=1, h=1))]
    pdf_bytes = generate_pdf_from_projection(
        matter_title="PT Count Case",
        projection=projection,
        gaps=[],
        appendix_entries=projection.entries,
        raw_events=raw_events,
        all_citations=citations,
        page_map={52: ("packet.pdf", 52)},
        evidence_graph_payload={},
        run_id=None,
    )
    text = _pdf_text(pdf_bytes)
    assert "PT visits (Verified): 117 encounters" in text


def test_billing_incomplete_avoids_misleading_total() -> None:
    projection = ChronologyProjection(generated_at=datetime.now(timezone.utc), entries=[])
    specials_summary = {
        "totals": {"total_charges": "377341.00", "total_payments": None, "total_adjustments": None, "total_balance": None},
        "by_provider": [],
        "coverage": {"billing_pages_count": 7, "earliest_service_date": "2024-10-11", "latest_service_date": "2024-10-11"},
        "dedupe": {"lines_raw": 10, "lines_deduped": 5},
        "confidence": 0.53,
        "flags": ["PARTIAL_BILLING_ONLY"],
    }
    pdf_bytes = generate_pdf_from_projection(
        matter_title="Billing Guard Case",
        projection=projection,
        gaps=[],
        appendix_entries=[],
        raw_events=[],
        all_citations=[],
        specials_summary=specials_summary,
        evidence_graph_payload={},
        run_id=None,
    )
    text = _pdf_text(pdf_bytes)
    assert "Billing extraction incomplete." in text
    assert "Not established in available records (incomplete billing documentation)." in text


def test_renderer_manifest_suppresses_sentinel_doi_display() -> None:
    projection = ChronologyProjection(generated_at=datetime.now(timezone.utc), entries=[])
    pdf_bytes = generate_pdf_from_projection(
        matter_title="DOI Guard Case",
        projection=projection,
        gaps=[],
        appendix_entries=[],
        raw_events=[],
        all_citations=[],
        renderer_manifest={"doi": {"value": "1900-01-01", "source": "inferred", "citation_ids": []}},
        evidence_graph_payload={},
        run_id=None,
    )
    text = _pdf_text(pdf_bytes)
    pre_appendix = text.split("Citation Index & Record Appendix")[0]
    assert "1900-01-01" not in pre_appendix
    assert "Date of injury could not be confirmed from available records." in text


def test_timeline_omits_uncited_rows() -> None:
    projection = ChronologyProjection(
        generated_at=datetime.now(timezone.utc),
        entries=[
            ChronologyProjectionEntry(
                event_id="evt-good",
                date_display="2024-01-02",
                event_type_display="Office Visit",
                provider_display="Clinic",
                facts=["Objective weakness 4/5 documented"],
                citation_display="records.pdf p. 5",
            ),
            ChronologyProjectionEntry(
                event_id="evt-bad",
                date_display="2024-01-03",
                event_type_display="Office Visit",
                provider_display="Clinic",
                facts=["Unsupported row should be omitted"],
                citation_display="Citation(s): Not available",
            ),
        ],
    )
    citations = [Citation(citation_id="cit-1", source_document_id="doc-1", page_number=5, snippet="Objective weakness 4/5", bbox=BBox(x=1, y=1, w=1, h=1))]
    raw_events = [
        Event(
            event_id="evt-good",
            provider_id="prov-1",
            event_type=EventType.OFFICE_VISIT,
            facts=[Fact(text="Objective weakness 4/5 documented", kind=FactKind.OTHER, verbatim=True, citation_ids=["cit-1"])],
            confidence=80,
            citation_ids=["cit-1"],
        )
    ]
    pdf_bytes = generate_pdf_from_projection(
        matter_title="Timeline Citation Case",
        projection=projection,
        gaps=[],
        appendix_entries=projection.entries,
        raw_events=raw_events,
        all_citations=citations,
        page_map={5: ("records.pdf", 5)},
        evidence_graph_payload={},
        run_id=None,
    )
    text = _pdf_text(pdf_bytes)
    assert "weakness 4/5" in text.lower()
    assert "Unsupported row should be omitted" not in text


def test_timeline_suppresses_sentinel_date_display() -> None:
    projection = ChronologyProjection(
        generated_at=datetime.now(timezone.utc),
        entries=[
            ChronologyProjectionEntry(
                event_id="evt-sentinel",
                date_display="1900-01-01 (time not documented)",
                event_type_display="Office Visit",
                provider_display="Clinic",
                facts=["Objective weakness 4/5 documented"],
                citation_display="records.pdf p. 5",
            ),
        ],
    )
    citations = [Citation(citation_id="cit-1", source_document_id="doc-1", page_number=5, snippet="Objective weakness 4/5", bbox=BBox(x=1, y=1, w=1, h=1))]
    raw_events = [
        Event(
            event_id="evt-sentinel",
            provider_id="prov-1",
            event_type=EventType.OFFICE_VISIT,
            facts=[Fact(text="Objective weakness 4/5 documented", kind=FactKind.OTHER, verbatim=True, citation_ids=["cit-1"])],
            confidence=80,
            citation_ids=["cit-1"],
        )
    ]
    pdf_bytes = generate_pdf_from_projection(
        matter_title="Sentinel Date Case",
        projection=projection,
        gaps=[],
        appendix_entries=projection.entries,
        raw_events=raw_events,
        all_citations=citations,
        page_map={5: ("records.pdf", 5)},
        evidence_graph_payload={},
        run_id=None,
    )
    text = _pdf_text(pdf_bytes)
    pre_appendix = text.split("Citation Index & Record Appendix")[0]
    assert "1900-01-01" not in pre_appendix


def test_snapshot_promoted_findings_follow_manifest_order() -> None:
    projection = ChronologyProjection(generated_at=datetime.now(timezone.utc), entries=[])
    citations = [
        Citation(citation_id="c-img", source_document_id="doc-1", page_number=12, snippet="MRI cervical spine with disc protrusion", bbox=BBox(x=1, y=1, w=1, h=1)),
        Citation(citation_id="c-obj", source_document_id="doc-1", page_number=14, snippet="Exam shows weakness 4/5 in right arm", bbox=BBox(x=1, y=1, w=1, h=1)),
    ]
    renderer_manifest = {
        "promoted_findings": [
            {
                "category": "imaging",
                "label": "C5-C6 disc protrusion with foraminal narrowing",
                "citation_ids": ["c-img"],
                "alignment_status": "PASS",
                "headline_eligible": True,
                "is_verbatim": False,
                "source_event_id": "evt-img",
            },
            {
                "category": "objective_deficit",
                "label": "Weakness 4/5 in right upper extremity",
                "citation_ids": ["c-obj"],
                "alignment_status": "PASS",
                "headline_eligible": True,
                "is_verbatim": False,
                "source_event_id": "evt-obj",
            },
        ]
    }
    pdf_bytes = generate_pdf_from_projection(
        matter_title="Manifest Order Case",
        projection=projection,
        gaps=[],
        appendix_entries=[],
        raw_events=[],
        all_citations=citations,
        page_map={12: ("records.pdf", 12), 14: ("records.pdf", 14)},
        renderer_manifest=renderer_manifest,
        evidence_graph_payload={},
        run_id=None,
    )
    text = _pdf_text(pdf_bytes)
    idx_img = text.find("Imaging: C5-C6 disc protrusion with foraminal narrowing")
    idx_obj = text.find("Objective Deficit: Weakness 4/5 in right upper extremity")
    assert idx_img != -1 and idx_obj != -1
    assert idx_img < idx_obj


def test_pdf_pt_verified_reported_reconciliation_and_ledger() -> None:
    projection = ChronologyProjection(generated_at=datetime.now(timezone.utc), entries=[])
    citations = [
        Citation(citation_id="cit-pt1", source_document_id="doc-1", page_number=52, snippet="PT daily note 11/19/2024", bbox=BBox(x=1, y=1, w=1, h=1)),
        Citation(citation_id="cit-pt2", source_document_id="doc-1", page_number=53, snippet="PT progress note 11/21/2024", bbox=BBox(x=1, y=1, w=1, h=1)),
        Citation(citation_id="cit-rpt", source_document_id="doc-1", page_number=88, snippet="PT discharge summary total visits 141", bbox=BBox(x=1, y=1, w=1, h=1)),
    ]
    pdf_bytes = generate_pdf_from_projection(
        matter_title="PT Reconciliation Case",
        projection=projection,
        gaps=[],
        appendix_entries=[],
        raw_events=[],
        all_citations=citations,
        page_map={52: ("packet.pdf", 52), 53: ("packet.pdf", 53), 88: ("packet.pdf", 88)},
        evidence_graph_payload={
            "extensions": {
                "pt_encounters": [
                    {
                        "encounter_date": "2024-11-19",
                        "provider_name": "Elite Physical Therapy",
                        "facility_name": "Elite Physical Therapy",
                        "encounter_kind": "PT",
                        "source": "primary",
                        "evidence_citation_ids": ["cit-pt1"],
                        "page_number": 52,
                        "dedupe_key": "a",
                    },
                    {
                        "encounter_date": "2024-11-21",
                        "provider_name": "Elite Physical Therapy",
                        "facility_name": "Elite Physical Therapy",
                        "encounter_kind": "PT",
                        "source": "primary",
                        "evidence_citation_ids": ["cit-pt2"],
                        "page_number": 53,
                        "dedupe_key": "b",
                    },
                ],
                "pt_count_reported": [
                    {
                        "reported_count": 141,
                        "report_source_type": "discharge_summary",
                        "evidence_citation_ids": ["cit-rpt"],
                        "page_number": 88,
                    }
                ],
                "pt_reconciliation": {
                    "verified_pt_count": 2,
                    "reported_pt_counts": [141],
                    "reported_pt_count_min": 141,
                    "reported_pt_count_max": 141,
                    "variance_flag": True,
                    "severe_variance_flag": True,
                },
                "litigation_safe_v1": {"status": "REVIEW_RECOMMENDED", "failure_reasons": [], "computed": {"max_gap_days": 0}},
            }
        },
        run_id=None,
    )
    text = _pdf_text(pdf_bytes)
    assert "PT visits (Verified): 2 encounters" in text
    assert "PT visits (Reported in records): 141" in text
    assert "PT Visit Ledger" in text
    assert "Dated PT encounters verified: 1" not in text


def test_pdf_suppresses_unverified_reported_pt_numeric_count() -> None:
    projection = ChronologyProjection(generated_at=datetime.now(timezone.utc), entries=[])
    citations = [
        Citation(citation_id="cit-rpt", source_document_id="doc-1", page_number=88, snippet="PT discharge summary total visits 141", bbox=BBox(x=1, y=1, w=1, h=1)),
    ]
    pdf_bytes = generate_pdf_from_projection(
        matter_title="PT Unverified Count Case",
        projection=projection,
        gaps=[],
        appendix_entries=[],
        raw_events=[],
        all_citations=citations,
        page_map={88: ("packet.pdf", 88)},
        evidence_graph_payload={
            "extensions": {
                "pt_encounters": [],
                "pt_count_reported": [
                    {
                        "reported_count": 141,
                        "report_source_type": "discharge_summary",
                        "evidence_citation_ids": ["cit-rpt"],
                        "page_number": 88,
                    }
                ],
                "pt_reconciliation": {
                    "verified_pt_count": 0,
                    "reported_pt_counts": [141],
                    "reported_pt_count_min": 141,
                    "reported_pt_count_max": 141,
                    "variance_flag": True,
                    "severe_variance_flag": True,
                },
                "litigation_safe_v1": {"status": "BLOCKED", "failure_reasons": [], "computed": {"max_gap_days": 0}},
            }
        },
        run_id=None,
    )
    text = _pdf_text(pdf_bytes)
    assert "PT visits (Reported in records): 141" not in text
    assert "PT visits (Reported): 141" not in text
    assert "ledger verification required" in text.lower()


def test_pdf_renders_case_severity_index_from_extension() -> None:
    projection = ChronologyProjection(generated_at=datetime.now(timezone.utc), entries=[])
    pdf_bytes = generate_pdf_from_projection(
        matter_title="CSI Section Case",
        projection=projection,
        gaps=[],
        appendix_entries=[],
        raw_events=[],
        all_citations=[],
        evidence_graph_payload={
            "extensions": {
                "case_severity_index": {
                    "schema_version": "csi.v2",
                    "base_csi": 6.9,
                    "risk_adjusted_csi": 6.4,
                    "band": "Moderate soft tissue with objective support",
                    "profile": "Profile: Radiculopathy documented; ED + imaging + PT course documented; 61-180 day treatment course.",
                    "component_scores": {
                        "objective": {"label": "Radiculopathy documented"},
                        "intensity": {"label": "ED + imaging + PT course documented"},
                        "duration": {"label": "61-180 day treatment course"},
                    },
                    "support": {"page_refs": [{"source_document_id": "doc-1", "page_number": 11}, {"source_document_id": "doc-1", "page_number": 95}]},
                }
            }
        },
        run_id=None,
    )
    text = _pdf_text(pdf_bytes)
    assert "CASE SEVERITY INDEX" in text
    assert "Case Severity Index: 6.9/10" in text
    assert "Risk-adjusted CSI: 6.4/10" in text


def test_pdf_mediation_renders_medical_severity_profile_without_csi() -> None:
    projection = ChronologyProjection(generated_at=datetime.now(timezone.utc), entries=[])
    pdf_bytes = generate_pdf_from_projection(
        matter_title="Mediation Severity Profile Case",
        projection=projection,
        gaps=[],
        appendix_entries=[],
        raw_events=[],
        all_citations=[],
        evidence_graph_payload={
            "extensions": {
                "severity_profile": {
                    "schema_version": "severity_profile.v1",
                    "export_intent": "mediation",
                    "primary_label": "Injection-tier treatment profile",
                    "band": "HIGH",
                    "severity_drivers": [
                        {"label": "Radiculopathy documented"},
                        {"label": "Injection / specialist intervention documented"},
                    ],
                    "treatment_progression": [{"label": "61-180 day treatment course"}],
                    "anticipated_defense_arguments": [
                        {
                            "argument": "Defense may argue treatment interruption weakens continuity.",
                            "context_supported_in_records": "Continuity concern appears in timeline chronology.",
                        }
                    ],
                    "support": {"page_refs": [{"source_document_id": "doc-1", "page_number": 11}]},
                }
            }
        },
        run_id=None,
        export_mode="MEDIATION",
    )
    text = _pdf_text(pdf_bytes)
    assert "MEDIATION EXPORT (NO VALUATION MODEL)" in text
    assert "MEDICAL SEVERITY PROFILE" in text
    assert "Profile derived from documented treatment progression and objective findings only; no valuation modeling applied." in text
    assert "CASE SEVERITY INDEX" not in text
    assert "Settlement Intelligence" not in text
    assert "SLI" not in text
    assert "Risk-adjusted CSI" not in text
    for banned in ["base_csi", "risk_adjusted", "score_0_100", "weights", "penalty_total"]:
        assert banned not in text
    sec_start = text.find("MEDICAL SEVERITY PROFILE")
    if sec_start != -1:
        section = text[sec_start : sec_start + 1200]
        import re
        assert re.search(r"\b\d+(?:\.\d+)?/10\b", section) is None


def test_pdf_mediation_rejects_banned_internal_csi_fields() -> None:
    projection = ChronologyProjection(generated_at=datetime.now(timezone.utc), entries=[])
    try:
        generate_pdf_from_projection(
            matter_title="Mediation Banned Keys Case",
            projection=projection,
            gaps=[],
            appendix_entries=[],
            raw_events=[],
            all_citations=[],
            evidence_graph_payload={
                "extensions": {
                    "severity_profile": {"schema_version": "severity_profile.v1", "primary_label": "Medical severity profile"},
                    "case_severity_index": {"base_csi": 8.1},
                }
            },
            run_id=None,
            export_mode="MEDIATION",
        )
    except RuntimeError as exc:
        assert "MEDIATION_RENDER_INPUT_BLOCKED" in str(exc)
    else:
        raise AssertionError("Expected mediation render input to be blocked for banned CSI keys")


def test_pdf_internal_contains_do_not_distribute_warning() -> None:
    projection = ChronologyProjection(generated_at=datetime.now(timezone.utc), entries=[])
    pdf_bytes = generate_pdf_from_projection(
        matter_title="Internal Warning Case",
        projection=projection,
        gaps=[],
        appendix_entries=[],
        raw_events=[],
        all_citations=[],
        evidence_graph_payload={"extensions": {"case_severity_index": {"base_csi": 5.5}}},
        run_id=None,
        export_mode="INTERNAL",
    )
    text = _pdf_text(pdf_bytes)
    assert "INTERNAL ANALYTICS — NOT FOR EXTERNAL DISTRIBUTION" in text
