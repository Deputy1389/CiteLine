from __future__ import annotations

import re
from collections import Counter

from packages.shared.models import Event


def classify_event(event: Event) -> str:
    et = event.event_type.value if hasattr(event.event_type, "value") else str(event.event_type)
    if et == "hospital_admission":
        return "inpatient"
    if et in {"hospital_discharge", "discharge"}:
        return "discharge_transfer"
    if et == "er_visit":
        return "ed_visit"
    if et == "procedure":
        return "surgery_procedure"
    if et == "imaging_study":
        return "imaging_impression"
    if et == "pt_visit":
        return "therapy"
    if et == "lab_result":
        return "labs"
    if et in {"office_visit", "inpatient_daily_note"}:
        return "clinic"
    return "other"


def severity_score(event: Event) -> int:
    event_class = classify_event(event)
    base = {
        "inpatient": 90,
        "discharge_transfer": 90,
        "ed_visit": 85,
        "surgery_procedure": 85,
        "imaging_impression": 75,
        "therapy": 60,
        "clinic": 55,
        "labs": 50,
        "other": 10,
    }[event_class]
    text = " ".join((f.text or "") for f in event.facts).lower()

    if re.search(r"\b(disposition|discharged|skilled nursing|snf|return to work|work restriction|follow-?up ordered)\b", text):
        base += 15
    if re.search(r"\b(new|newly|started|initiated|stopped|discontinued|increased|decreased|switched|changed to)\b", text):
        base += 15
    severe_score = False
    for m in re.finditer(r"\b(phq-?9|gad-?7|pain(?:\s+severity|\s+score)?)\s*[:=]?\s*(\d{1,2})\b", text):
        try:
            if int(m.group(2)) >= 15:
                severe_score = True
                break
        except ValueError:
            continue
    if severe_score or re.search(r"\b(suicid|homeless)\b", text):
        base += 10
    if re.search(
        r"\b(left|right|bilateral)\b.*\b(fracture|tear|injury|dislocation|infection|pain|wound)\b|\b(fracture|tear|injury|dislocation|infection|pain|wound)\b.*\b(left|right|bilateral)\b",
        text,
    ):
        base += 10
    if re.search(r"\b(critical|panic|high-risk|abnormal|elevated)\b", text) and event_class == "labs":
        base += 10

    if re.search(r"\bclinical follow-?up documenting continuity, symptoms, and treatment response\b", text):
        base -= 30
    if re.search(r"\b(body height|body weight|blood pressure|respiratory rate|heart rate|temperature|bmi|weight percentile)\b", text):
        base -= 25
    if re.search(r"\b(phq-?9|gad-?7|questionnaire|survey score|promis|pain interference)\b", text) and not severe_score:
        base = min(base, 20)
    if not event.citation_ids:
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
