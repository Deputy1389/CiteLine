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
        # 1) Full date wins
        v = self.value
        if v is not None:
            if isinstance(v, date):
                return (0, v.isoformat())
            return (0, v.start.isoformat())
        
        # 2) True relative day (positive) is allowed ONLY when it is genuinely relative to an anchor
        rd = self.relative_day
        if rd is not None:
            if rd >= 0:
                # interpret as offset from 1900-01-01 for stable sorting
                try:
                    d = date(1900, 1, 1) + timedelta(days=rd - 1)
                    return (1, f"REL:{rd:06d}")
                except Exception:
                    pass
            else:
                # Defensive: should not happen
                return (9, f"RELNEG:{rd}")

        # 3) Partial date: month/day ordering, no year fabricated
        ext = self.extensions or {}
        if ext.get("partial_date") and ext.get("partial_month") and ext.get("partial_day"):
            m = int(ext["partial_month"])
            d = int(ext["partial_day"])
            return (2, f"PART:{m:02d}-{d:02d}")

        # Fallback to model fields if extensions missing but fields set
        if self.partial_month is not None:
            return (2, f"PART:{self.partial_month:02d}-{self.partial_day:02d}")
            
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
