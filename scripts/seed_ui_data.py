from packages.db.database import get_session, init_db
from packages.db.models import Matter, Firm

def seed():
    init_db()
    with get_session() as session:
        firm = session.query(Firm).filter_by(id="firm_ui_test").first()
        if not firm:
            firm = Firm(id="firm_ui_test", name="UI Test Firm")
            session.add(firm)
        
        matter = session.query(Matter).filter_by(id="matter_ui_test").first()
        if not matter:
            matter = Matter(id="matter_ui_test", firm_id="firm_ui_test", title="Doe v. Big Corp")
            session.add(matter)
        
        session.commit()
        print("Seeded firm_ui_test and matter_ui_test")

if __name__ == "__main__":
    seed()
