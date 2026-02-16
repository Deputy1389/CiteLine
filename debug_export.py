
import sys
import os
from datetime import date
from packages.shared.models import Event, Provider, EventType, EventDate, DateKind, DateSource, Fact, FactKind
from apps.worker.steps.step12_export import render_exports

def date_obj(d):
    return EventDate(kind=DateKind.SINGLE, value=d, source=DateSource.TIER1)

def run():
    print("Generating debug exports...")
    
    # Mock data
    events = [
        Event(
            event_id="evt_1",
            event_type=EventType.OFFICE_VISIT,
            date=date_obj(date(2023, 1, 15)),
            provider_id="prov_1",
            facts=[Fact(text="Patient complained of pain.", kind=FactKind.CHIEF_COMPLAINT, verbatim=True, citation_id="cit_1")],
            source_page_numbers=[1, 2],
            citation_ids=["cit_1"],
            confidence=85,
        ),
        Event(
            event_id="evt_2",
            event_type=EventType.PROCEDURE,
            date=date_obj(date(2023, 2, 20)),
            provider_id="prov_2",
            facts=[Fact(text="Surgery performed.", kind=FactKind.PROCEDURE_NOTE, verbatim=False, citation_id="cit_2")],
            source_page_numbers=[11], # Global page 11
            citation_ids=["cit_2"],
            confidence=90,
        )
    ]
    
    providers = [
        Provider(provider_id="prov_1", detected_name_raw="Dr. Smith", normalized_name="Dr. Smith", confidence=100),
        Provider(provider_id="prov_2", detected_name_raw="Hospital", normalized_name="General Hospital", confidence=100),
    ]
    
    # Page map: Global Page -> (Filename, Local Page)
    # Assume Doc A has 10 pages, Doc B has 10 pages.
    # Page 1 -> Doc A, p.1
    # Page 11 -> Doc B, p.1
    page_map = {
        1: ("DocA.pdf", 1),
        2: ("DocA.pdf", 2),
        11: ("DocB.pdf", 1),
    }
    
    try:
        # Mock storage? render_exports calls save_artifact which writes to disk.
        # We need to make sure save_artifact works or is mocked.
        # It writes to local storage. run_id="debug_run".
        
        output = render_exports(
            run_id="debug_provenance_run",
            matter_title="Debug Matter",
            events=events,
            gaps=[],
            providers=providers,
            page_map=page_map,
        )
        print("Export successful.")
        print(f"PDF URI: {output.exports.pdf.uri}")
        print(f"CSV URI: {output.exports.csv.uri}")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    run()
