from datetime import datetime, timezone

from apps.worker.project.models import ChronologyProjection, ChronologyProjectionEntry
from apps.worker.steps.export_render.render_manifest import RenderManifest, chron_anchor, appendix_anchor
from apps.worker.steps.export_render.timeline_pdf import _build_projection_flowables
from apps.worker.steps.export_render.timeline_pdf import _manifest_finding_paragraphs
from apps.worker.steps.export_render.timeline_pdf import _entry_fact_flag_pairs, _quote_if_verbatim
from reportlab.lib.styles import getSampleStyleSheet
from packages.shared.models.domain import Citation
from packages.shared.models.common import BBox


def _citation(doc_id: str, page: int, snippet: str = "Test snippet") -> Citation:
    return Citation(
        citation_id=f"c-{doc_id}-{page}",
        source_document_id=doc_id,
        page_number=page,
        snippet=snippet,
        bbox=BBox(x=0, y=0, w=10, h=10),
    )


def test_render_manifest_links_from_citations() -> None:
    entries = [
        ChronologyProjectionEntry(
            event_id="evt1",
            date_display="2024-01-01",
            event_type_display="Imaging Study",
            provider_display="Provider A",
            facts=["Impression: MRI shows disc protrusion at L4-5."],
            citation_display="records.pdf p. 2",
        ),
    ]
    projection = ChronologyProjection(entries=entries, generated_at=datetime.now(timezone.utc))
    manifest = RenderManifest()
    all_citations = [_citation("records.pdf", 2)]

    _build_projection_flowables(
        projection=projection,
        raw_events=None,
        page_map=None,
        styles=getSampleStyleSheet(),
        manifest=manifest,
        all_citations=all_citations,
    )

    c_anchor = chron_anchor("evt1")
    a_anchor = appendix_anchor("records.pdf", 2)
    assert c_anchor in manifest.chron_anchors
    assert a_anchor in manifest.forward_links.get(c_anchor, [])


def test_manifest_finding_paragraphs_can_exclude_snapshot_semantic_families() -> None:
    styles = getSampleStyleSheet()
    rm = {
        "promoted_findings": [
            {
                "category": "imaging",
                "label": "Loss of cervical lordosis with spasm",
                "citation_ids": ["c-doc-10"],
                "headline_eligible": True,
                "semantic_family": "imaging|cervical|positive|spasm_lordosis",
                "finding_source_count": 1,
                "source_families": ["imaging"],
            },
            {
                "category": "imaging",
                "label": "C5-C6 disc protrusion with foraminal narrowing",
                "citation_ids": ["c-doc-11"],
                "headline_eligible": True,
                "semantic_family": "imaging|cervical|positive|disc_pathology",
                "finding_source_count": 1,
                "source_families": ["imaging"],
            },
        ]
    }
    citation_by_id = {
        "c-doc-10": {"doc_id": "records.pdf", "local_page": 10, "display": "records.pdf p. 10"},
        "c-doc-11": {"doc_id": "records.pdf", "local_page": 11, "display": "records.pdf p. 11"},
    }
    rows = _manifest_finding_paragraphs(
        rm,
        categories=("imaging",),
        styles=styles,
        manifest=None,
        citation_by_id=citation_by_id,
        limit=8,
        include_secondary=False,
        headline_only=True,
        exclude_semantic_families={"imaging|cervical|positive|spasm_lordosis"},
    )
    text = " ".join(getattr(r, "text", "") for r in rows)
    assert "disc protrusion" in text.lower()
    assert "lordosis" not in text.lower()


def test_entry_fact_verbatim_quote_helpers() -> None:
    entry = ChronologyProjectionEntry(
        event_id="evtv1",
        date_display="2024-01-01",
        event_type_display="Emergency Visit",
        provider_display="General Hospital",
        facts=["Rear-end collision with neck pain 8/10.", "Assessment cervical strain."],
        verbatim_flags=[True, False],
        citation_display="records.pdf p. 2",
    )
    pairs = _entry_fact_flag_pairs(entry)
    assert pairs[0] == ("Rear-end collision with neck pain 8/10.", True)
    assert pairs[1] == ("Assessment cervical strain.", False)
    assert _quote_if_verbatim(pairs[0][0], pairs[0][1]).startswith('"Rear-end collision')
    assert _quote_if_verbatim(pairs[1][0], pairs[1][1]) == "Assessment cervical strain."
