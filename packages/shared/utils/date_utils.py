import re
from datetime import date
from apps.worker.steps.events.report_quality import date_sanity

def parse_fact_dates(text: str) -> list[date]:
    if not text:
        return []
    out: list[date] = []
    for m in re.finditer(r"\b(20\d{2}|19\d{2})-([01]\d)-([0-3]\d)(?:\b|T)", text):
        yy, mm, dd = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            out.append(date(yy, mm, dd))
        except ValueError:
            pass
    for m in re.finditer(r"\b([01]?\d)/([0-3]?\d)/(20\d{2}|19\d{2})\b", text):
        mm, dd, yy = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            out.append(date(yy, mm, dd))
        except ValueError:
            pass
    return [d for d in out if date_sanity(d)]

def fact_temporally_consistent(fact_text: str, target_date: date | None) -> bool:
    if target_date is None:
        return True
    fact_dates = parse_fact_dates(fact_text)
    if not fact_dates:
        return True
    return any(abs((fd - target_date).days) <= 30 for fd in fact_dates)

def strip_conflicting_timestamps(fact_text: str, target_date: date | None) -> str:
    if target_date is None:
        return fact_text
    cleaned = fact_text
    for m in re.finditer(r"\b(\d{4}-\d{2}-\d{2})[Tt]\d{2}:\d{2}:\d{2}[Zz]\b", fact_text):
        try:
            ts_date = date.fromisoformat(m.group(1))
        except ValueError:
            continue
        if abs((ts_date - target_date).days) > 1:
            cleaned = cleaned.replace(m.group(0), "")
    for m in re.finditer(r"\b(\d{4}-\d{2}-\d{2})\b", cleaned):
        try:
            ts_date = date.fromisoformat(m.group(1))
        except ValueError:
            continue
        if abs((ts_date - target_date).days) > 30:
            cleaned = cleaned.replace(m.group(0), "")
    cleaned = re.sub(r"\(\s*\)", "", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned
