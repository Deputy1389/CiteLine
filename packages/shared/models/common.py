from datetime import date, timedelta
from typing import Optional

from pydantic import BaseModel, Field

from .enums import DateKind, DateSource


class BBox(BaseModel):
    x: float
    y: float
    w: float
    h: float


class DateRange(BaseModel):
    start: date
    end: Optional[date] = None


class EventDate(BaseModel):
    kind: DateKind
    value: date | DateRange | None = None
    relative_day: int | None = None  # e.g. 1 for "Day 1"
    source: DateSource

    def sort_key(self) -> tuple[date, int]:
        """Return a sortable tuple. Uses year 1900 for relative dates."""
        v = self.value
        if v is not None:
            if isinstance(v, date):
                return (v, 0)
            return (v.start, 0)
        
        rd = self.relative_day
        if rd is not None:
            # Sort relative dates as if they were in 1900
            # relative_day 1 -> 1900-01-01
            try:
                d = date(1900, 1, 1) + timedelta(days=rd - 1)
                return (d, 1)  # 1 indicates relative
            except Exception:
                return (date.min, 0)
        return (date.min, 0)

    def sort_date(self) -> date:
        """Deprecated. Use sort_key()."""
        k, _ = self.sort_key()
        return k
