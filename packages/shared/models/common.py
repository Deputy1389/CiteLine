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
    relative_day: int | None = None  # e.g. 1 for "Day 1" (ADMISSION RELATIVE ONLY)
    source: DateSource
    partial_month: int | None = None
    partial_day: int | None = None
    extensions: dict | None = None

    def sort_key(self) -> tuple[int, str]:
        """Return a sortable tuple. Strict priority logic."""
        ext = self.extensions or {}
        time_val = str(ext.get("time", "0000")).replace(":", "")
        
        # 1) Full date wins
        v = self.value
        if v is not None:
            if isinstance(v, date):
                return (0, f"{v.isoformat()} {time_val}")
            return (0, f"{v.start.isoformat()} {time_val}")
        
        # 2) True relative day (positive) is allowed ONLY when it is genuinely relative to an anchor
        rd = self.relative_day
        if rd is not None and rd >= 0:
            return (1, f"{rd:06d} {time_val}")

        # 3) Partial date: month/day ordering, no year fabricated
        if ext.get("partial_date") and ext.get("partial_month") and ext.get("partial_day"):
            m = int(ext["partial_month"])
            d = int(ext["partial_day"])
            return (2, f"{m:02d}-{d:02d} {time_val}")

        # Fallback to model fields if extensions missing but fields set
        if self.partial_month is not None:
            return (2, f"{self.partial_month:02d}-{self.partial_day:02d} {time_val}")
            
        return (99, "UNKNOWN")

    def sort_date(self) -> date:
        """Return a calendar date for calculation. Returns date(1900, 1, 1) for relative/partial."""
        v = self.value
        if v is not None:
            if isinstance(v, date):
                return v
            return v.start
        
        rd = self.relative_day
        if rd is not None and rd >= 0:
            try:
                return date(1900, 1, 1) + timedelta(days=rd - 1)
            except Exception:
                pass
        
        return date(1900, 1, 1)
