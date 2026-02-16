from datetime import date
from datetime import date
from packages.shared.models.common import EventDate, DateKind, DateSource
from packages.shared.models import Event, EventType
from apps.worker.steps.step12_export import _date_str

def test_export_render():
    # Partial Date
    ed = EventDate(kind=DateKind.SINGLE, source=DateSource.TIER2, extensions={"partial_date": True, "partial_month": 5, "partial_day": 20})
    evt = Event(event_id="1", provider_id="prov1", event_type=EventType.OFFICE_VISIT, date=ed, facts=[], citation_ids=[], source_page_numbers=[1], confidence=90)
    
    s = _date_str(evt)
    print(f"Rendered Partial: '{s}'")
    assert s == "05/20 (year unknown)", f"Failed partial render: {s}"
    
    # Relative Day
    ed2 = EventDate(kind=DateKind.SINGLE, source=DateSource.TIER2, relative_day=5)
    evt2 = Event(event_id="2", provider_id="prov1", event_type=EventType.OFFICE_VISIT, date=ed2, facts=[], citation_ids=[], source_page_numbers=[1], confidence=90)
    s2 = _date_str(evt2)
    print(f"Rendered Relative: '{s2}'")
    assert s2 == "Day 5", f"Failed relative render: {s2}"

    print("SUCCESS: Export rendering verified.")

if __name__ == "__main__":
    test_export_render()
