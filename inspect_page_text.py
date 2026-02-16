from packages.db.database import get_db
from packages.db.models import Page

def inspect_text():
    db_gen = get_db()
    db = next(db_gen)
    
    try:
        run_id = "812837b7c9af4c2fab962b1a8af4abf9"
        search_term = "complained of pain"
        print(f"Searching for '{search_term}' in Run {run_id}")
        
        pages = db.query(Page).filter(Page.run_id == run_id, Page.text.ilike(f"%{search_term}%")).all()
        
        if not pages:
             print("No pages found.")
             return

        for p in pages:
             print(f"=== PAGE {p.page_number} id={p.id} ===")
             print("--- HEADER ---")
             print("\n".join(p.text.splitlines()[:10]))
            
    finally:
        db.close()

if __name__ == "__main__":
    inspect_text()
