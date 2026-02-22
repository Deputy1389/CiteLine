import os
from datetime import datetime, timezone, date

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///C:/CiteLine/data/test_persist_hardening.db")

from packages.db.database import engine, get_session, init_db
from packages.db.models import Base, Firm, Matter, Run, SourceDocument, Page, Event, Citation
from packages.shared.models.domain import (
    EvidenceGraph,
    Page as PageModel,
    PageLayout,
    Document,
    PageTypeSpan,
    Provider,
    ProviderEvidence,
    Event as EventModel,
    EventDate,
    Fact,
    Citation as CitationModel,
    BBox,
    Gap,
    Warning,
    Metrics,
    Provenance,
    RunRecord,
    ArtifactRef,
)
from packages.shared.models.enums import PageType, ProviderType, EventType, FactKind, RunStatus
from apps.worker.pipeline_persistence import persist_pipeline_state


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def _make_run_record(run_id: str) -> RunRecord:
    return RunRecord(
        run_id=run_id,
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
        status="success",
        warnings=[],
        metrics=Metrics(
            documents=1,
            pages_total=1,
            pages_ocr=0,
            events_total=1,
            events_exported=1,
            providers_total=1,
            processing_seconds=1.0,
        ),
        provenance=Provenance(),
    )


def _make_evidence_graph(doc_id: str, run_id: str) -> EvidenceGraph:
    page = PageModel(
        page_id="p1",
        source_document_id=doc_id,
        page_number=1,
        text="Clinical note: patient reports back pain.",
        text_source="embedded_pdf_text",
        layout=PageLayout(width=612, height=792),
        page_type=PageType.CLINICAL_NOTE,
    )
    doc = Document(
        document_id="d1",
        source_document_id=doc_id,
        page_start=1,
        page_end=1,
        page_types=[PageTypeSpan(page_start=1, page_end=1, page_type=PageType.CLINICAL_NOTE)],
    )
    prov = Provider(
        provider_id="prov1",
        detected_name_raw="Dr. Smith",
        normalized_name="Smith, MD",
        provider_type=ProviderType.PHYSICIAN,
        confidence=80,
        evidence=[ProviderEvidence(page_number=1, snippet="Dr. Smith", bbox=BBox(x=1, y=1, w=10, h=10))],
    )
    cit = CitationModel(
        citation_id="c1",
        source_document_id=doc_id,
        page_number=1,
        snippet="patient reports back pain",
        bbox=BBox(x=1, y=1, w=10, h=10),
    )
    evt = EventModel(
        event_id="e1",
        provider_id=prov.provider_id,
        event_type=EventType.CLINICAL_NOTE,
        date=EventDate(kind="absolute", value=date.today(), source="extracted"),
        encounter_type_raw="Clinical Note",
        facts=[Fact(text="Patient reports back pain.", kind=FactKind.OTHER, verbatim=False, citation_id="c1")],
        diagnoses=[],
        procedures=[],
        imaging=None,
        billing=None,
        confidence=80,
        flags=[],
        citation_ids=["c1"],
        source_page_numbers=[1],
        extensions={},
    )
    return EvidenceGraph(
        documents=[doc],
        pages=[page],
        providers=[prov],
        events=[evt],
        citations=[cit],
        gaps=[],
    )


def test_persist_pipeline_state_idempotent():
    with get_session() as session:
        firm = Firm(name="Persist Firm")
        session.add(firm)
        session.flush()
        matter = Matter(firm_id=firm.id, title="Persist Case")
        session.add(matter)
        session.flush()
        doc = SourceDocument(
            matter_id=matter.id,
            filename="doc.pdf",
            mime_type="application/pdf",
            sha256="0" * 64,
            bytes=100,
        )
        session.add(doc)
        session.flush()
        run = Run(matter_id=matter.id, status="running")
        session.add(run)
        session.flush()
        run_id = run.id
        doc_id = doc.id

    record = _make_run_record(run_id)
    graph = _make_evidence_graph(doc_id, run_id)
    artifact_entries = [("pdf", ArtifactRef(uri="s3://x", sha256="0" * 64, bytes=123))]
    persist_pipeline_state(run_id, "success", 1.0, record, [], graph, artifact_entries)
    persist_pipeline_state(run_id, "success", 1.0, record, [], graph, artifact_entries)

    with get_session() as session:
        assert session.query(Page).filter_by(run_id=run_id).count() == 1
        assert session.query(Event).filter_by(run_id=run_id).count() == 1
        assert session.query(Citation).filter_by(run_id=run_id).count() == 1
