import io
from datetime import datetime, timezone

from pypdf import PdfReader

from apps.worker.lib.claim_context_alignment import run_claim_context_alignment
from apps.worker.lib.litigation_safe_v1 import validate_litigation_safe_v1
from apps.worker.project.models import ChronologyProjection
from apps.worker.steps.export_render.timeline_pdf import generate_pdf_from_projection


def _pdf_text(pdf_bytes: bytes) -> str:
    return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(pdf_bytes)).pages)


def _base_graph() -> dict:
    return {
        "pages": [
            {"page_number": 1, "page_type": "billing", "text": "Billing claim for MVA personal injury"},
            {"page_number": 2, "page_type": "clinical_note", "text": "History: motor vehicle collision. Patient rear-ended at stoplight."},
            {"page_number": 3, "page_type": "clinical_note", "text": "Assessment: M51.26 lumbar intervertebral disc displacement."},
            {"page_number": 4, "page_type": "imaging_report", "text": "MRI cervical spine shows disc material extending into neural foramen."},
        ],
        "citations": [
            {"citation_id": "c1", "page_number": 1, "snippet": "MVA billing header"},
            {"citation_id": "c2", "page_number": 2, "snippet": "motor vehicle collision"},
            {"citation_id": "c3", "page_number": 3, "snippet": "M51.26 lumbar intervertebral disc displacement"},
            {"citation_id": "c4", "page_number": 4, "snippet": "disc material extending into neural foramen"},
            {"citation_id": "c5", "page_number": 4, "snippet": "disc bulge"},
        ],
    }


def test_claim_context_mechanism_page_type_mismatch_blocked() -> None:
    graph = _base_graph()
    rm = {"mechanism": {"value": "motor vehicle collision", "citation_ids": ["c1"]}, "promoted_findings": []}
    out = run_claim_context_alignment(graph, rm)
    assert out["export_status"] == "BLOCKED"
    assert out["claims_fail"] == 1
    assert out["failures"][0]["reason_code"] == "page_type_mismatch"
    assert out["failures"][0]["claim_type"] == "mechanism"


def test_claim_context_diagnosis_exact_icd_match_passes() -> None:
    graph = _base_graph()
    rm = {
        "mechanism": {"value": None, "citation_ids": []},
        "promoted_findings": [{"category": "diagnosis", "label": "M51.26 Lumbar Intervertebral Disc Displacement", "citation_ids": ["c3"]}],
    }
    out = run_claim_context_alignment(graph, rm)
    assert out["export_status"] == "PASS"
    assert out["claims_pass"] == 1


def test_claim_context_imaging_partial_overlap_passes_threshold() -> None:
    graph = _base_graph()
    rm = {
        "promoted_findings": [{"category": "imaging", "label": "disc material extending into neural foramen", "citation_ids": ["c4"]}],
    }
    out = run_claim_context_alignment(graph, rm)
    assert out["export_status"] == "PASS"
    assert out["claims_pass"] == 1


def test_claim_context_overstatement_blocks() -> None:
    graph = _base_graph()
    rm = {
        "promoted_findings": [{"category": "imaging", "label": "significant disc material extending into neural foramen", "citation_ids": ["c5"]}],
    }
    out = run_claim_context_alignment(graph, rm)
    assert out["export_status"] == "BLOCKED"
    assert out["failures"][0]["reason_code"] == "overstatement_risk"


def test_litigation_safe_v1_embeds_claim_context_failures_and_pdf_lists_specific_bullets() -> None:
    claim_check = {
        "name": "claim_context_alignment",
        "export_status": "BLOCKED",
        "claims_total": 1,
        "claims_pass": 0,
        "claims_fail": 1,
        "failures": [
            {
                "claim_id": "abc123",
                "claim_type": "mechanism",
                "claim_text": "motor vehicle collision",
                "citations": [1],
                "page_types": ["billing"],
                "candidate_pages": [{"page": 1, "page_type": "billing", "score": 0.5}],
                "best_page": 1,
                "best_page_type": "billing",
                "best_score": 0.5,
                "reason_code": "page_type_mismatch",
                "severity": "BLOCKED",
            }
        ],
        "PASS": False,
    }
    lsv1 = validate_litigation_safe_v1(
        snapshot={"mechanism": "", "mechanism_citation_ids": [], "diagnoses": []},
        events=[],
        extractionContext={"billingStatus": "NONE", "claimContextAlignment": claim_check},
    )
    mech_failure = next(f for f in lsv1["failure_reasons"] if f.get("code") == "MECHANISM_OR_DIAGNOSIS_UNSUPPORTED")
    assert mech_failure.get("claim_failures")
    projection = ChronologyProjection(generated_at=datetime.now(timezone.utc), entries=[])
    pdf_bytes = generate_pdf_from_projection(
        matter_title="Claim Context",
        projection=projection,
        gaps=[],
        appendix_entries=[],
        raw_events=[],
        all_citations=[],
        evidence_graph_payload={"extensions": {"litigation_safe_v1": lsv1}},
        run_id=None,
        include_internal_review_sections=True,
    )
    text = _pdf_text(pdf_bytes)
    assert "Defense Vulnerabilities Identified" in text
    assert "What was detected" in text

