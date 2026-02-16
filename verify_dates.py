from datetime import date
from packages.shared.models.common import EventDate, DateKind, DateSource

def test_strict_sorting():
    # 1. Full Date
    d1 = EventDate(kind=DateKind.SINGLE, source=DateSource.TIER1, value=date(2023, 1, 1))
    
    # 2. Partial Date (MM/DD)
    # extensions logic simulation
    d2 = EventDate(kind=DateKind.SINGLE, source=DateSource.TIER2, extensions={"partial_date": True, "partial_month": 12, "partial_day": 25})
    
    # 3. Relative Day (Positive)
    d3 = EventDate(kind=DateKind.SINGLE, source=DateSource.TIER2, relative_day=5)
    
    # 4. Unknown
    d4 = EventDate(kind=DateKind.SINGLE, source=DateSource.TIER2)

    # Sort
    items = [d4, d3, d2, d1]
    sorted_items = sorted(items, key=lambda x: x.sort_key())
    
    print("Sorted keys:")
    for i in sorted_items:
        print(i.sort_key())

    assert sorted_items[0] == d1, "Full date should be first"
    assert sorted_items[1] == d3, "Positive relative day should be second"
    assert sorted_items[2] == d2, "Partial date should be third"
    assert sorted_items[3] == d4, "Unknown should be last"
    print("SUCCESS: Strict sorting verified.")

if __name__ == "__main__":
    test_strict_sorting()
