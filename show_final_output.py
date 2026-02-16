from packages.db.database import get_db
from packages.db.models import Event

def show_events():
    db_gen = get_db()
    db = next(db_gen)
    
    try:
        # Search for events on 9/24 for specific run
        run_id = "812837b7c9af4c2fab962b1a8af4abf9"
        from packages.db.models import Run, Page, SourceDocument
        run = db.query(Run).filter(Run.id == run_id).first()
        if run:
             print(f"Run Status: {run.status}")
             print(f"Run Error: {run.error_message}")
             
        # List warnings from JSON
        import json
        warnings = run.warnings_json or []
        if isinstance(warnings, str):
            try:
                warnings = json.loads(warnings)
            except:
                print(f"Failed to parse warnings: {warnings[:100]}")
                warnings = []
                
        print(f"Warnings: {len(warnings)}")
        for i, w in enumerate(warnings[:20]):
             print(f" - Warning {i}: {w.get('code')}: {w.get('message')} (Page {w.get('page')})")
             
        # List documents
        doc_ids = db.query(Page.source_document_id).filter(Page.run_id == run_id).distinct().all()
        doc_ids = [d[0] for d in doc_ids]
        print(f"Documents in run: {len(doc_ids)}")
        for did in doc_ids:
            doc = db.query(SourceDocument).filter(SourceDocument.id == did).first()
            print(f" - {did}: {doc.filename if doc else 'Unknown'}")
            
        # Try to find page with "Ann Davis"
        target_text = "Ann Davis"
        page = db.query(Page).filter(Page.run_id == run_id, Page.text.ilike(f"%{target_text}%")).first()
        if page:
             print(f"Found '{target_text}' on Page {page.page_number} of Doc {page.source_document_id}")
             # Now get events for THIS page
             page_events = db.query(Event).filter(Event.run_id == run_id).all()
             # Filter in python for source page
             relevant_events = [e for e in page_events if page.page_number in (e.source_page_numbers_json or [])]
             print(f"Events for Page {page.page_number}: {len(relevant_events)}")
        else:
             print(f"'{target_text}' NOT FOUND in run.")
        
        return # Stop here for now to analyze

        
        relevant_events = []
        for e in events:
            # Pydantic models are serialized to JSON columns in DB
            # We access the dicts directly
            dj = e.date_json or {}
            ext = dj.get("extensions") or {}
            # Dump everything
            relevant_events.append(e)

        if not relevant_events:
            print("No events found for 9/24.")
            return

        # Sort by time
        def get_time(e):
            dj = e.date_json or {}
            ext = dj.get("extensions") or {}
            return ext.get("time", "0000")
            
        relevant_events.sort(key=get_time)

        for e in relevant_events:
             dj = e.date_json or {}
             ext = dj.get("extensions") or {}
             time = ext.get("time", "??")
             
             fj = e.facts_json or []
             # Fact is dict: {'text': ..., 'kind': ...}
             facts = "\n  ".join([f.get("text", "") for f in fj])
             
             spn = e.source_page_numbers_json or []
             
             print(f"{ext.get('partial_month')}/{ext.get('partial_day')} {time} [Pages: {spn}] {facts}")

    finally:
        db.close()

if __name__ == "__main__":
    show_events()
