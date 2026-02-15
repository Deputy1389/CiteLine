"""
Integration test: full pipeline end-to-end with validation of DB persistence.
Based on test_pipeline_e2e.py, but adds checks for Evidence Graph tables.
"""
from __future__ import annotations

import json
import os
import sys
import uuid
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import text

# Setup test environment before imports
# Use a separate test DB for persistence test
os.environ.setdefault("DATABASE_URL", "sqlite:///C:/CiteLine/data/test_persistence.db")
os.environ.setdefault("DATA_DIR", "C:/CiteLine/data")

from packages.db.database import engine, init_db, get_session
from packages.db.models import (
    Base, Firm, Matter, SourceDocument, Run,
    Page, DocumentSegment, Provider, Event, Citation, Gap
)
from packages.shared.storage import save_upload, sha256_bytes


@pytest.fixture(autouse=True)
def setup_db():
    """Create fresh tables for each test."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    # also remove the file if possible, or just truncate tables
    # SQLite file persists, but assert checking tables is enough


def _generate_fixture_pdf() -> bytes:
    """Generate the synthetic PDF using the fixture generator."""
    from tests.fixtures.generate_fixture import create_synthetic_pdf
    return create_synthetic_pdf()


class TestPersistenceE2E:
    def test_pipeline_persistence(self):
        """Full end-to-end run, then check DB for evidence graph rows."""
        pdf_bytes = _generate_fixture_pdf()
        file_hash = sha256_bytes(pdf_bytes)

        # Setup: create firm, matter, source document
        with get_session() as session:
            firm = Firm(name="Persistence Law Firm")
            session.add(firm)
            session.flush()

            matter = Matter(
                firm_id=firm.id,
                title="Persistence Test Case",
            )
            session.add(matter)
            session.flush()

            doc = SourceDocument(
                matter_id=matter.id,
                filename="persistence_test.pdf",
                mime_type="application/pdf",
                sha256=file_hash,
                bytes=len(pdf_bytes),
            )
            session.add(doc)
            session.flush()

            # Save PDF to disk
            path = save_upload(doc.id, pdf_bytes)
            doc.storage_uri = str(path)

            # Create run
            run_config = {
                "max_pages": 500,
                "pt_mode": "aggregate", 
                "gap_threshold_days": 45
            }
            run = Run(
                matter_id=matter.id,
                status="pending",
                config_json=json.dumps(run_config),
            )
            session.add(run)
            session.flush()
            run_id = run.id
            doc_id = doc.id


        # Execute pipeline
        from apps.worker.pipeline import run_pipeline
        run_pipeline(run_id)

        # Verify DB Persistence
        with get_session() as session:
            run = session.query(Run).filter_by(id=run_id).first()
            assert run.status in ("success", "partial"), f"Run failed with error: {run.error_message}"

            # 1. Pages
            pages = session.query(Page).filter_by(run_id=run_id).all()
            assert len(pages) > 0, "No pages persisted"
            print(f"Persisted {len(pages)} pages")
            # Check fields
            assert pages[0].text is not None
            assert pages[0].source_document_id == doc_id

            # 2. Document Segments
            segments = session.query(DocumentSegment).filter_by(run_id=run_id).all()
            assert len(segments) > 0, "No segments persisted"
            print(f"Persisted {len(segments)} segments")

            # 3. Providers
            providers = session.query(Provider).filter_by(run_id=run_id).all()
            # Synthetic PDF might have providers
            if len(providers) > 0:
                print(f"Persisted {len(providers)} providers")
                assert providers[0].detected_name_raw is not None

            # 4. Events
            events = session.query(Event).filter_by(run_id=run_id).all()
            # Should have some events if fixture works
            if len(events) > 0:
                print(f"Persisted {len(events)} events")
                assert events[0].event_type is not None
                assert events[0].date_json is not None
                # Check provider link if exists
                if events[0].provider_id:
                    prov = session.query(Provider).filter_by(id=events[0].provider_id).first()
                    assert prov is not None, "Event references missing provider"

            # 5. Citations
            citations = session.query(Citation).filter_by(run_id=run_id).all()
            if len(citations) > 0:
                print(f"Persisted {len(citations)} citations")
                assert citations[0].snippet is not None

            # 6. Gaps
            gaps = session.query(Gap).filter_by(run_id=run_id).all()
            # Might be 0 gaps depending on dates
            print(f"Persisted {len(gaps)} gaps")
