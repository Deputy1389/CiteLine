from apps.worker.project.models import ChronologyProjection, ChronologyProjectionEntry
from apps.worker.steps.export_render.render_manifest import RenderManifest, chron_anchor, appendix_anchor
from apps.worker.steps.export_render.timeline_pdf import _build_projection_flowables
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
    projection = ChronologyProjection(entries=entries)
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
