"""
Extract events from Lab Reports.
"""
from __future__ import annotations

import re
import uuid
from datetime import date

from packages.shared.models import (
    Citation,
    Event,
    EventDate,
    EventType,
    Fact,
    FactKind,
    Page,
    PageType,
    Provider,
    SkippedEvent,
    Warning,
)
from .common import _make_citation, _make_fact, _find_section

# Common lab tests to look for
_LAB_TESTS = [
    # Hematology / CBC
    "WBC", "White Blood Cell", "RBC", "Red Blood Cell", "Hemoglobin", "Hematocrit",
    "Platelet", "MCV", "MCH", "MCHC", "RDW", "MPV", "Neutrophil", "Lymphocyte",
    "Monocyte", "Eosinophil", "Basophil",

    # Chemistry / Metabolic Panel
    "Glucose", "Calcium", "Sodium", "Potassium", "Chloride", "CO2", "Bicarbonate",
    "BUN", "Creatinine", "GFR", "Albumin", "Bilirubin", "Alkaline Phosphatase",
    "AST", "ALT", "Protein", "Globulin", "Magnesium", "Phosphorus",

    # Lipid Panel
    "Cholesterol", "HDL", "LDL", "VLDL", "Triglyceride",

    # Coagulation
    "PT", "PTT", "INR", "Prothrombin", "D-Dimer", "Fibrinogen",

    # Urinalysis
    "Urinalysis", "Urine", "Specific Gravity", "Leukocyte Esterase", "Nitrite",
    "Ketone", "Protein/Creatinine", "Microalbumin",

    # Thyroid
    "TSH", "T3", "T4", "Free T4", "Thyroid",

    # Cardiac
    "Troponin", "BNP", "NT-proBNP", "CK-MB", "Myoglobin",

    # Inflammatory / Infection
    "CRP", "ESR", "Procalcitonin", "Lactate", "Lactic Acid",

    # Tumor Markers
    "CEA", "CA 19-9", "CA-125", "PSA", "AFP",

    # Other Common Tests
    "HbA1c", "Hemoglobin A1c", "Vitamin D", "B12", "Folate", "Iron", "Ferritin",
    "TIBC", "Ammonia", "Amylase", "Lipase",
]

def extract_lab_events(
    pages: list[Page],
    dates: dict[int, list[EventDate]],
    providers: list[Provider],
    page_provider_map: dict[int, str],
) -> tuple[list[Event], list[Citation], list[Warning], list[SkippedEvent]]:
    """
    Extract events from pages classified as LAB_REPORT.
    """
    events: list[Event] = []
    citations: list[Citation] = []
    warnings: list[Warning] = []
    skipped: list[SkippedEvent] = []

    # Process pages identified as LAB_REPORT
    lab_pages = [p for p in pages if p.page_type == PageType.LAB_REPORT]

    for page in lab_pages:
        page_dates = dates.get(page.page_number, [])
        # Prefer collection date or result date
        event_date = page_dates[0] if page_dates else None
        
        provider_id = page_provider_map.get(page.page_number, "unknown")
        
        # Extract specific tests found on page
        found_tests = []
        text_lower = page.text.lower()
        # "PT" means Physical Therapy in a PT context, not Prothrombin Time.
        # Guard triggers on PT_NOTE pages OR on any page containing strong PT-therapy language.
        is_pt_context = (
            page.page_type == PageType.PT_NOTE
            or "physical therapy" in text_lower
            or "pt sessions" in text_lower
            or "therapy sessions" in text_lower
        )
        for test in _LAB_TESTS:
            if test == "PT" and is_pt_context:
                continue
            # "PT" alone is ambiguous (Physical Therapy vs Prothrombin Time).
            # Require explicit coagulation context to count it as a lab test.
            if test == "PT":
                coag_context = any(
                    kw in text_lower
                    for kw in ("ptt", "inr", "prothrombin", "coagul", "fibrin", "anticoagul")
                )
                if not coag_context:
                    continue
            if test.lower() in text_lower:
                found_tests.append(test)

        # Expanded trigger patterns for lab reports
        lab_indicators = [
            "specimen", "reference range", "reference interval", "result", "value",
            "normal", "abnormal", "high", "low", "collection date", "collection time",
            "lab", "laboratory", "test", "panel", "screen", "culture", "blood draw",
            "serum", "plasma", "whole blood", "units", "mg/dl", "mmol/l", "g/dl",
            "cells/ul", "fasting", "non-fasting"
        ]

        # If no tests found, maybe just a summary
        facts = []
        citation_ids = []

        if found_tests:
            # Create a summary fact
            summary_text = f"Labs found: {', '.join(found_tests[:5])}"
            if len(found_tests) > 5:
                summary_text += f" (+{len(found_tests)-5} more)"

            cit = _make_citation(page, summary_text)
            citations.append(cit)
            fact = _make_fact(summary_text, FactKind.LAB, cit.citation_id)
            facts.append(fact)
            citation_ids.append(cit.citation_id)
        else:
            # Fallback: check for lab report indicators
            indicator_count = sum(1 for indicator in lab_indicators if indicator in text_lower)
            if indicator_count >= 2:  # At least 2 indicators = likely a lab report
                cit = _make_citation(page, "Lab report content detected")
                citations.append(cit)
                fact = _make_fact("Lab report with results detected", FactKind.LAB, cit.citation_id)
                facts.append(fact)
                citation_ids.append(cit.citation_id)

        if not facts:
            skipped.append(SkippedEvent(
                page_numbers=[page.page_number],
                reason_code="NO_TRIGGER_MATCH",
                snippet=page.text[:100]
            ))
            continue

        # Create event
        events.append(Event(
            event_id=uuid.uuid4().hex,
            provider_id=provider_id,
            event_type=EventType.LAB_RESULT,
            date=event_date,
            facts=facts,
            confidence=60,
            citation_ids=citation_ids,
            source_page_numbers=[page.page_number],
        ))

    return events, citations, warnings, skipped
