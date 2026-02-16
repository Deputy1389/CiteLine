"""
Unit tests for missing record detection (Phase 3).
"""
import pytest
from datetime import date

from apps.worker.steps.step15_missing_records import (
    _detect_global_gaps,
    _detect_provider_gaps,
    _detect_continuity_mentions,
    detect_missing_records,
)
from packages.shared.models import (
    BBox,
    Citation,
    DateKind,
    DateSource,
    EvidenceGraph,
    Event,
    EventDate,
    EventType,
    Fact,
    FactKind,
    Page,
    PageType,
    Provider,
    ProviderEvidence,
    ProviderType,
)


def _evt(eid, d=None, pid="p1", cit_ids=None, pages=None):
    return Event(
        event_id=eid,
        provider_id=pid,
        event_type=EventType.OFFICE_VISIT,
        date=EventDate(kind=DateKind.SINGLE, value=d, source=DateSource.TIER1) if d else None,
        facts=[Fact(text="test", kind=FactKind.CHIEF_COMPLAINT, verbatim=True, citation_id="c1")],
        confidence=80,
        flags=[] if d else ["MISSING_DATE"],
        citation_ids=cit_ids or ["c1"],
        source_page_numbers=pages or [1],
    )


def _page(num, text="Sample text", ptype=PageType.CLINICAL_NOTE):
    return Page(
        page_id=f"page-{num}",
        source_document_id="doc-1",
        page_number=num,
        text=text,
        text_source="embedded_pdf_text",
        page_type=ptype,
    )


# ── Global gap detection ─────────────────────────────────────────────────


class TestGlobalGaps:
    def test_no_gap_below_threshold(self):
        graph = EvidenceGraph(events=[
            _evt("e1", date(2024, 1, 1)),
            _evt("e2", date(2024, 1, 10)),
        ])
        findings = _detect_global_gaps(graph, threshold_days=14)
        assert len(findings) == 0

    def test_gap_above_threshold(self):
        graph = EvidenceGraph(events=[
            _evt("e1", date(2024, 1, 1), cit_ids=["c1"]),
            _evt("e2", date(2024, 3, 1), cit_ids=["c2"]),
        ])
        findings = _detect_global_gaps(graph, threshold_days=14)
        assert len(findings) == 1
        assert findings[0]["finding_type"] == "global_gap"
        assert findings[0]["gap_days"] == 60
        assert findings[0]["reason_code"] == "GAP_OVER_THRESHOLD"
        assert "c1" in findings[0]["citation_ids"]
        assert "c2" in findings[0]["citation_ids"]

    def test_multiple_gaps(self):
        graph = EvidenceGraph(events=[
            _evt("e1", date(2024, 1, 1)),
            _evt("e2", date(2024, 3, 1)),
            _evt("e3", date(2024, 6, 1)),
        ])
        findings = _detect_global_gaps(graph, threshold_days=14)
        assert len(findings) == 2

    def test_single_event_no_gap(self):
        graph = EvidenceGraph(events=[_evt("e1", date(2024, 1, 1))])
        findings = _detect_global_gaps(graph, threshold_days=14)
        assert len(findings) == 0

    def test_dateless_events_ignored(self):
        graph = EvidenceGraph(events=[
            _evt("e1", date(2024, 1, 1)),
            _evt("e2"),  # no date
            _evt("e3", date(2024, 6, 1)),
        ])
        findings = _detect_global_gaps(graph, threshold_days=14)
        assert len(findings) == 1


# ── Provider gap detection ────────────────────────────────────────────────


class TestProviderGaps:
    def test_provider_gap_detected(self):
        graph = EvidenceGraph(
            providers=[Provider(
                provider_id="p1",
                detected_name_raw="Dr. Smith",
                normalized_name="dr smith",
                provider_type=ProviderType.PHYSICIAN,
                confidence=80,
            )],
            events=[
                _evt("e1", date(2024, 1, 1), pid="p1"),
                _evt("e2", date(2024, 4, 1), pid="p1"),
            ],
        )
        providers_normalized = [{
            "normalized_name": "dr smith",
            "display_name": "Dr. Smith",
            "provider_type": "physician",
            "first_seen_date": "2024-01-01",
            "last_seen_date": "2024-04-01",
            "event_count": 2,
            "citation_count": 2,
            "source_provider_ids": ["p1"],
        }]
        findings = _detect_provider_gaps(graph, providers_normalized, default_threshold_days=30)
        assert len(findings) == 1
        assert findings[0]["finding_type"] == "provider_gap"
        assert findings[0]["provider_entity_id"] == "dr smith"
        assert findings[0]["gap_days"] == 91

    def test_pt_provider_lower_threshold(self):
        graph = EvidenceGraph(
            providers=[Provider(
                provider_id="p1",
                detected_name_raw="PT Clinic",
                normalized_name="pt clinic",
                provider_type=ProviderType.UNKNOWN,
                confidence=80,
            )],
            events=[
                _evt("e1", date(2024, 1, 1), pid="p1"),
                _evt("e2", date(2024, 1, 15), pid="p1"),
            ],
        )
        providers_normalized = [{
            "normalized_name": "pt clinic",
            "display_name": "PT Clinic",
            "provider_type": "pt",
            "first_seen_date": "2024-01-01",
            "last_seen_date": "2024-01-15",
            "event_count": 2,
            "citation_count": 2,
            "source_provider_ids": ["p1"],
        }]
        findings = _detect_provider_gaps(graph, providers_normalized, pt_threshold_days=7)
        assert len(findings) == 1
        assert findings[0]["reason_code"] == "PT_COURSE_GAP"


# ── Continuity mention detection ──────────────────────────────────────────


class TestContinuityMentions:
    def test_followup_detected(self):
        graph = EvidenceGraph(
            pages=[_page(1, "Patient should follow up in 2 weeks.")],
            citations=[Citation(
                citation_id="c1", source_document_id="doc-1",
                page_number=1, snippet="follow up",
                bbox=BBox(x=0, y=0, w=100, h=20),
            )],
        )
        findings = _detect_continuity_mentions(graph)
        assert len(findings) >= 1
        assert any(f["reason_code"] == "FOLLOWUP_MENTION" for f in findings)

    def test_imaging_ordered_detected(self):
        graph = EvidenceGraph(
            pages=[_page(1, "Doctor ordered an MRI of the lumbar spine.")],
        )
        findings = _detect_continuity_mentions(graph)
        assert len(findings) >= 1
        assert any(f["reason_code"] == "IMAGING_ORDERED" for f in findings)

    def test_pt_continuation_detected(self):
        graph = EvidenceGraph(
            pages=[_page(1, "Continue physical therapy 3x per week.")],
        )
        findings = _detect_continuity_mentions(graph)
        assert len(findings) >= 1
        assert any(f["reason_code"] == "PT_COURSE_GAP" for f in findings)

    def test_no_triggers_on_clean_text(self):
        graph = EvidenceGraph(
            pages=[_page(1, "Chief complaint: low back pain. Exam normal.")],
        )
        findings = _detect_continuity_mentions(graph)
        assert len(findings) == 0

    def test_deduplication_same_page(self):
        graph = EvidenceGraph(
            pages=[_page(1, "Follow up in 4 weeks. Patient should follow up in 6 weeks.")],
        )
        findings = _detect_continuity_mentions(graph)
        # Should deduplicate same trigger type on same page
        followup_findings = [f for f in findings if f["reason_code"] == "FOLLOWUP_MENTION"]
        assert len(followup_findings) == 1


# ── Integration: full detect_missing_records ──────────────────────────────


class TestDetectMissingRecords:
    def test_deterministic_ordering(self):
        graph = EvidenceGraph(
            pages=[_page(1, "Return in 2 weeks for follow up.")],
            events=[
                _evt("e1", date(2024, 1, 1)),
                _evt("e2", date(2024, 6, 1)),
            ],
        )
        r1 = detect_missing_records(graph, [])
        r2 = detect_missing_records(graph, [])
        # Exclude generated_at and ids from comparison
        for r in [r1, r2]:
            for f in r["findings"]:
                f.pop("id", None)
            r.pop("generated_at", None)
        assert r1 == r2

    def test_findings_have_required_fields(self):
        graph = EvidenceGraph(
            pages=[_page(1, "Ordered MRI lumbar spine")],
            events=[
                _evt("e1", date(2024, 1, 1)),
                _evt("e2", date(2024, 6, 1)),
            ],
            citations=[Citation(
                citation_id="c1", source_document_id="doc-1",
                page_number=1, snippet="MRI",
                bbox=BBox(x=0, y=0, w=100, h=20),
            )],
        )
        result = detect_missing_records(graph, [])
        for finding in result["findings"]:
            assert "id" in finding
            assert "finding_type" in finding
            assert "reason_code" in finding
            assert "confidence" in finding
            # Must have citation_ids OR source_page_numbers
            has_refs = (
                len(finding.get("citation_ids", [])) > 0
                or len(finding.get("source_page_numbers", [])) > 0
            )
            assert has_refs, f"Finding {finding['id']} has no citation or page ref"

    def test_metrics_correct(self):
        graph = EvidenceGraph(
            pages=[_page(1, "Follow up in 3 weeks.")],
            events=[
                _evt("e1", date(2024, 1, 1)),
                _evt("e2", date(2024, 6, 1)),
            ],
        )
        result = detect_missing_records(graph, [])
        m = result["metrics"]
        assert m["total_findings"] == m["global_gaps"] + m["provider_gaps"] + m["continuity_mentions"]
