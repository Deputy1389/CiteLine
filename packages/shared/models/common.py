from datetime import date
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
    value: date | DateRange
    source: DateSource

    def sort_date(self) -> date:
        """Return a single date for sorting."""
        if isinstance(self.value, date):
            return self.value
        return self.value.start
