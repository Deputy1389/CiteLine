from __future__ import annotations

import re
from collections import Counter

from packages.shared.models import Event


def classify_event(event: Event) -> str:
    et = event.event_type.value if hasattr(event.event_type, "value") else str(event.event_type)
    if et in {"hospital_admission", "hospital_discharge", "discharge"}:
        return "admission_discharge"
    if et == "er_visit":
        return "er_visit"
    if et == "procedure":
        return "procedure"
    if et == "imaging_study":
        return "imaging"
    if et == "pt_visit":
        return "therapy"
    if et == "lab_result":
        return "lab"
    if et == "office_visit":
        return "clinic"
    return "other"


def severity_score(event: Event) -> int:
    event_class = classify_event(event)
    base = {
        "admission_discharge": 90,
        "er_visit": 85,
        "procedure": 80,
        "imaging": 65,
        "therapy": 55,
        "clinic": 45,
        "lab": 35,
        "other": 20,
    }[event_class]
    text = " ".join((f.text or "") for f in event.facts).lower()
    if re.search(r"\b(phq-?9\s*[:=]?\s*1[5-9]|suicid|homeless)\b", text):
        base = max(base, 75)
    if re.search(r"\b(opioid|hydrocodone|oxycodone|morphine)\b", text):
        base += 5
    if re.search(r"\b(body height|body weight|blood pressure|respiratory rate|heart rate|temperature|bmi)\b", text):
        base -= 15
    return max(0, min(100, base))


def annotate_event_weights(events: list[Event]) -> dict:
    by_class = Counter()
    scores: list[int] = []
    for event in events:
        event_class = classify_event(event)
        score = severity_score(event)
        event.extensions = dict(event.extensions or {})
        event.extensions["event_class"] = event_class
        event.extensions["severity_score"] = score
        event.extensions["is_care_event"] = score >= 40
        by_class[event_class] += 1
        scores.append(score)
    avg_score = round(sum(scores) / len(scores), 2) if scores else 0.0
    return {
        "event_count": len(events),
        "avg_severity_score": avg_score,
        "by_class": dict(sorted(by_class.items(), key=lambda item: item[0])),
    }
