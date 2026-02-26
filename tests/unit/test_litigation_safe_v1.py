from datetime import date, datetime, timezone
import io

from pypdf import PdfReader

from apps.worker.lib.litigation_safe_v1 import validate_litigation_safe_v1
from apps.worker.project.models import ChronologyProjection
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
    return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(pdf_bytes)).pages)


def _fact(text: str, cid: str) -> Fact:
    return Fact(text=text, kind=FactKind.OTHER, verbatim=True, citation_ids=[cid])


def _event(event_id: str, etype: EventType, d: date | None, fact_text: str, cid: str, *, icd10: list[str] | None = None) -> Event:
    return Event(
        event_id=event_id,
        provider_id="prov-1",
        event_type=etype,
        date=(EventDate(kind=DateKind.SINGLE, value=d, source=DateSource.TIER1) if d else None),
        facts=[_fact(fact_text, cid)],
        diagnoses=[Fact(text=f"Diagnosis {','.join(icd10 or [])}" if icd10 else "Cervical radiculopathy", kind=FactKind.DIAGNOSIS, verbatim=True, citation_ids=[cid])],
        coding={"icd10": icd10 or []},
        confidence=90,
        citation_ids=[cid],
        source_page_numbers=[1],
    )


def _valid_snapshot() -> dict:
    return {
        "mechanism": "motor vehicle collision",
        "mechanism_citation_ids": ["cit-mech"],
        "diagnoses": ["M54.12 Cervical radiculopathy"],
        "pt_total_encounters": 117,
    }


def _valid_events() -> list[Event]:
    return [
        _event("er1", EventType.ER_VISIT, date(2024, 10, 11), "Patient evaluated after motor vehicle collision; neck pain.", "cit-mech", icd10=["M54.12"]),
        _event("img1", EventType.IMAGING_STUDY, date(2024, 10, 21), "MRI cervical spine reviewed.", "cit-img"),
        _event("proc1", EventType.PROCEDURE, date(2024, 11, 1), "Epidural steroid injection performed.", "cit-proc"),
        _event("pt1", EventType.PT_VISIT, date(2024, 11, 19), "PT sessions documented: 117", "cit-pt"),
    ]


def _base_ctx() -> dict:
    return {
        "billingStatus": "COMPLETE",
        "gaps": [{"duration_days": 18}],
        "billingPresentation": {
            "visibleIncompleteDisclosure": True,
            "noGlobalTotalSpecials": True,
            "partialTotalsLabeled": True,
        },
    }


def _codes(result: dict) -> set[str]:
    return {str(x.get('code')) for x in (result.get('failure_reasons') or []) if isinstance(x, dict)}


def test_litigation_safe_v1_verified_passes() -> None:
    res = validate_litigation_safe_v1(_valid_snapshot(), _valid_events(), _base_ctx())
    assert res["status"] == "VERIFIED"
    assert res["failure_reasons"] == []
    assert res["checks"]["mechanism_and_diagnosis_supported"] is True


def test_litigation_safe_v1_partial_billing_is_review_recommended() -> None:
    ctx = _base_ctx()
    ctx["billingStatus"] = "PARTIAL"
    res = validate_litigation_safe_v1(_valid_snapshot(), _valid_events(), ctx)
    assert res["status"] == "REVIEW_RECOMMENDED"
    assert res["failure_reasons"] == []
    assert res["billing_partial_disclosed"] is True


def test_litigation_safe_v1_fails_mechanism_or_diagnosis_unsupported() -> None:
    snap = _valid_snapshot()
    snap["mechanism_citation_ids"] = ["cit-missing"]
    snap["diagnoses"] = ["M50.20 Disc disorder"]
    res = validate_litigation_safe_v1(snap, _valid_events(), _base_ctx())
    assert res["status"] == "BLOCKED"
    assert "MECHANISM_OR_DIAGNOSIS_UNSUPPORTED" in _codes(res)


def test_litigation_safe_v1_fails_missing_procedure_date() -> None:
    events = _valid_events()
    events[2] = _event("proc1", EventType.PROCEDURE, None, "Epidural steroid injection performed.", "cit-proc")
    res = validate_litigation_safe_v1(_valid_snapshot(), events, _base_ctx())
    assert res["status"] == "BLOCKED"
    assert "PROCEDURE_DATE_MISSING" in _codes(res)


def test_litigation_safe_v1_fails_gap_inconsistency() -> None:
    events = [
        _event("e1", EventType.ER_VISIT, date(2024, 1, 1), "Motor vehicle collision", "cit-mech", icd10=["M54.12"]),
        _event("e2", EventType.PT_VISIT, date(2024, 3, 20), "PT sessions documented: 117", "cit-pt"),
    ]
    ctx = _base_ctx()
    ctx["gaps"] = [{"duration_days": 0}]
    res = validate_litigation_safe_v1(_valid_snapshot(), events, ctx)
    assert res["status"] == "BLOCKED"
    assert "GAP_STATEMENT_INCONSISTENT" in _codes(res)


def test_litigation_safe_v1_fails_billing_implied_complete() -> None:
    ctx = _base_ctx()
    ctx["billingStatus"] = "PARTIAL"
    ctx["billingPresentation"] = {
        "visibleIncompleteDisclosure": False,
        "noGlobalTotalSpecials": False,
        "partialTotalsLabeled": False,
    }
    res = validate_litigation_safe_v1(_valid_snapshot(), _valid_events(), ctx)
    assert res["status"] == "BLOCKED"
    assert "BILLING_IMPLIED_COMPLETE" in _codes(res)


def test_litigation_safe_v1_fails_internal_contradiction() -> None:
    ctx = _base_ctx()
    ctx["ptCountCandidates"] = [117, 141]
    res = validate_litigation_safe_v1(_valid_snapshot(), _valid_events(), ctx)
    assert res["status"] == "BLOCKED"
    assert "INTERNAL_CONTRADICTION" in _codes(res)


def test_litigation_safe_v1_multi_failure() -> None:
    snap = _valid_snapshot()
    snap["mechanism_citation_ids"] = ["bad-cid"]
    events = _valid_events()
    events[1] = _event("img1", EventType.IMAGING_STUDY, None, "MRI cervical spine reviewed.", "cit-img")
    ctx = _base_ctx()
    ctx["billingStatus"] = "PARTIAL"
    ctx["billingPresentation"] = {"visibleIncompleteDisclosure": False, "noGlobalTotalSpecials": False, "partialTotalsLabeled": False}
    ctx["ptCountCandidates"] = [117, 141]
    res = validate_litigation_safe_v1(snap, events, ctx)
    codes = _codes(res)
    assert res["status"] == "BLOCKED"
    assert {"MECHANISM_OR_DIAGNOSIS_UNSUPPORTED", "PROCEDURE_DATE_MISSING", "BILLING_IMPLIED_COMPLETE", "INTERNAL_CONTRADICTION"}.issubset(codes)


def test_pdf_shows_litigation_safety_check_section_and_reasons() -> None:
    projection = ChronologyProjection(generated_at=datetime.now(timezone.utc), entries=[])
    pdf_bytes = generate_pdf_from_projection(
        matter_title="Litigation Safe PDF",
        projection=projection,
        gaps=[],
        appendix_entries=[],
        raw_events=[],
        all_citations=[Citation(citation_id="cit-mech", source_document_id="doc", page_number=1, snippet="mvc", bbox=BBox(x=1, y=1, w=1, h=1))],
        evidence_graph_payload={
            "extensions": {
                "litigation_safe_v1": {
                    "status": "BLOCKED",
                    "failure_reasons": [
                        {"code": "PROCEDURE_DATE_MISSING", "message": "Procedure date missing."},
                    ],
                    "computed": {"max_gap_days": 0},
                }
            }
        },
        run_id=None,
    )
    text = _pdf_text(pdf_bytes)
    assert "Litigation Safety Check" in text
    assert "Status: BLOCKED" in text
    assert "PROCEDURE_DATE_MISSING" in text
    assert "Export Status = BLOCKED" in text
