"""
Step 3 — Page type classification (rule-based).
Assign page_type using priority-ordered keyword heuristics.
"""
from __future__ import annotations

import re

from packages.shared.models import Page, PageType, Warning

# Priority-ordered classification rules: (page_type, keywords_tuple)
_RULES: list[tuple[PageType, tuple[str, ...]]] = [
    (PageType.OPERATIVE_REPORT, (
        "operative report", "procedure note", "anesthesia", "pre-op", "post-op",
        "surgical", "operation", "preoperative", "postoperative", "surgeon:",
        "anesthesiologist:", "operative findings", "indication for surgery",
        "procedure performed", "procedure:", "operative procedure", "surgery:",
        "incision", "specimen:", "estimated blood", "specimens", "procedure",
    )),
    (PageType.IMAGING_REPORT, (
        "impression", "findings", "technique", "radiology", "mri ", " ct ",
        "x-ray", "ultrasound", "imaging", "study date", "radiologist",
        "contrast", "comparison:", "clinical history:", "modality",
    )),
    (PageType.LAB_REPORT, (
        "lab results", "complete blood count", "cbc", "cmp", "bmp",
        "urinalysis", "hemoglobin", "hematocrit", "reference range",
        "specimen", "collected date", "resulted", "glucose",
        "platelet", "white blood cell", "wbc", "lipid panel",
        "creatinine", "sodium", "potassium", "test name", "value",
    )),
    (PageType.DISCHARGE_SUMMARY, (
        "discharge summary", "hospital course", "discharge diagnosis",
        "discharge instructions", "final diagnosis", "condition on discharge",
        "discharge medications", "admission date", "discharge date",
        "hospital day", "discharged to", "disposition:",
    )),
    (PageType.BILLING, (
        "statement", "charges", "balance", "total due", "cpt", "hcfa",
        "ub-04", "invoice", "ledger", "amount due", "billing",
        "payment", "insurance", "account number", "service date",
    )),
    (PageType.PT_NOTE, (
        "physical therapy", "pt daily note", "exercise", "plan of care",
        "visit #", "rehabilitation", "therapeutic exercise",
        "gait training", "mobility", "ambulation", "therapist",
        # Expanded PT note keywords
        "range of motion", "rom:", "rom ", "treat dx", "treatment dx",
        "medical dx", "hep", "home exercise program",
        "functional activity", "manual therapy", "therapeutic activities",
        "patient tolerated", "modalities", "ultrasound therapy",
        "electrical stimulation", "neuromuscular", "strengthening",
        "flexion", "extension", "kinesio", "taping", "set(s) of",
        "repetitions", "pt note", "discharge plan", "treatment session",
        "initial evaluation", "re-evaluation", "pt progress",
        "treatment note", "soap note", "functional outcomes",
    )),
    (PageType.ADMINISTRATIVE, (
        "fax cover", "authorization", "release of information", " roi ",
        "request for records", "records sent", "hipaa", "consent form",
        "medical records request", "authorization to release",
    )),
    (PageType.CLINICAL_NOTE, (
        "chief complaint", "history of present illness", "assessment",
        "plan:", "ros ", "review of systems", "physical exam",
        "vital signs", "medications", "allergies", "flowsheet", "nursing",
        "progress note", "subjective:", "objective:", "diagnosis:",
        "patient complaint", "exam:", "impression:", "attending:",
        "provider:", "blood pressure", "temperature", "pulse",
        "respiratory rate", "pain level", "alert and oriented",
        # SOAP note shorthand
        "cc:", "hpi:", "pmh:", "psh:", "meds:", "ros:",
        "s:", "o:", "a:", "p:",
        # Consultation / specialist notes
        "consultation", "consult note", "consulting physician",
        "referred by", "reason for referral", "referring physician",
        "requesting physician", "consulting service",
        # Office visit / follow-up
        "office visit", "follow up visit", "follow-up visit",
        "date of service", "date of visit", "dos:", "return visit",
        # Emergency / urgent care
        "emergency", "triage", "urgent care", "chief complaint:",
        "disposition:", "er visit", "ed visit",
        # Ortho / spine / neurology
        "orthopedic", "neurology", "chiropractic", "pain management",
        "spine", "cervical", "lumbar", "radiculopathy",
        # Inpatient notes
        "hospital day", "inpatient", "nursing note", "rn note",
        "attending note", "resident note", "intern note",
        # Injury / PI context
        "accident", "mechanism of injury", "injured", "injury date",
        "initial evaluation", "return to work", "work status",
    )),
]

# Medical terminology patterns - if present, suggests clinical content
_MEDICAL_INDICATORS = [
    # Symptoms
    r"\b(pain|nausea|vomiting|fever|cough|dyspnea|fatigue|weakness|dizzy|headache)\b",
    # Diagnoses
    r"\b(cancer|carcinoma|adenocarcinoma|tumor|metastatic|malignancy|neoplasm)\b",
    r"\b(diabetes|hypertension|copd|chf|pneumonia|infection|sepsis)\b",
    # Medications
    r"\b(mg|mcg|ml|dose|prn|tid|bid|qid|daily|twice daily)\b",
    r"\b(morphine|oxycodone|hydrocodone|fentanyl|warfarin|insulin|metformin)\b",
    # Medical procedures/treatments
    r"\b(chemotherapy|radiation|dialysis|intubation|ventilator|oxygen)\b",
    # Anatomy
    r"\b(lung|heart|liver|kidney|brain|spine|abdomen|chest|pelvis)\b",
    # Clinical observations
    r"\b(alert|oriented|ambulatory|bedridden|stable|unstable|improving|deteriorating)\b",
]

# Compile patterns once
_MEDICAL_PATTERN = re.compile("|".join(_MEDICAL_INDICATORS), re.IGNORECASE)


def classify_page(page: Page) -> tuple[PageType, int]:
    """
    Classify a single page. Returns (page_type, confidence).
    Confidence: 80+ for strong match, 50 for weak.

    Strategy:
    1. Check keyword-based rules (highest priority)
    2. If no match, check for medical terminology
    3. Default to CLINICAL_NOTE if medical content detected (instead of OTHER)
    """
    text_lower = page.text.lower()
    best_type = PageType.OTHER
    best_conf = 30

    # Step 1: Try keyword-based classification
    for page_type, keywords in _RULES:
        matches = sum(1 for kw in keywords if kw in text_lower)
        conf = 0
        if matches >= 2:
            conf = min(90, 60 + matches * 10)
        elif matches == 1:
            conf = 50

        # If we already have a strong match, only switch if this one is stronger
        if conf > best_conf:
            best_type = page_type
            best_conf = conf

    # Step 2: If still classified as OTHER, check for medical terminology
    if best_type == PageType.OTHER:
        medical_matches = _MEDICAL_PATTERN.findall(page.text)
        if len(medical_matches) >= 1:  # Lowered from 3 — any medical term = clinical
            # Page has medical terminology but no specific type match.
            # Default to CLINICAL_NOTE so clinical extractor processes it.
            best_type = PageType.CLINICAL_NOTE
            best_conf = 40  # Low confidence but enough to process

    return best_type, best_conf


def classify_pages(pages: list[Page]) -> tuple[list[Page], list[Warning]]:
    """
    Classify all pages and assign page_type.
    Returns (updated_pages, warnings).
    """
    warnings: list[Warning] = []

    for page in pages:
        page_type, confidence = classify_page(page)
        page.page_type = page_type

        if confidence < 50:
            warnings.append(Warning(
                code="PAGE_TYPE_LOW_CONF",
                message=f"Page {page.page_number} classified as '{page_type.value}' with low confidence ({confidence})",
                page=page.page_number,
                document_id=page.source_document_id,
            ))

    return pages, warnings
