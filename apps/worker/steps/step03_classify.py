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
    (PageType.DISCHARGE_SUMMARY, (
        "discharge summary", "hospital course", "discharge diagnosis",
        "discharge instructions", "final diagnosis", "condition on discharge",
        "discharge medications", "admission date", "discharge date",
        "hospital day", "discharged to", "disposition:",
        "admission record", "clinical summary",
    )),
    (PageType.LAB_REPORT, (
        "lab results", "complete blood count", "cbc", "cmp", "bmp",
        "urinalysis", "hemoglobin", "hematocrit", "reference range",
        "specimen", "collected date", "resulted", "glucose",
        "platelet", "white blood cell", "wbc", "lipid panel",
        "creatinine", "sodium", "potassium", "test name", "value",
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
_HARD_HEADER_RULES: list[tuple[PageType, tuple[str, ...]]] = [
    (PageType.OPERATIVE_REPORT, ("operative report", "operative findings", "procedure performed")),
    (PageType.DISCHARGE_SUMMARY, ("discharge summary", "discharge instructions", "clinical summary")),
    (PageType.IMAGING_REPORT, ("radiology", "mri ", " ct ", "x-ray", "ultrasound")),
    (PageType.BILLING, ("statement of charges", "total due", "invoice", "amount due")),
    (PageType.PT_NOTE, ("pt daily note", "plan of care", "treatment session")),
    (PageType.ADMINISTRATIVE, ("fax cover", "authorization request", "release of information")),
]


def _header_text(text: str, max_lines: int = 12) -> str:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return "\n".join(lines[:max_lines]).lower()


def _score_page_types(text: str) -> dict[PageType, int]:
    text_lower = (text or "").lower()
    header_lower = _header_text(text)
    scores: dict[PageType, int] = {}
    for page_type, keywords in _RULES:
        score = 0
        unique_hits = 0
        for kw in keywords:
            body_hits = text_lower.count(kw)
            if body_hits <= 0:
                continue
            unique_hits += 1
            score += min(body_hits, 2) * 12
            if kw in header_lower:
                score += 20
            if len(kw) >= 12:
                score += 6
        if unique_hits:
            score += unique_hits * 6
        scores[page_type] = score
    return scores


def classify_page(page: Page) -> tuple[PageType, int]:
    """
    Classify a single page. Returns (page_type, confidence).
    Confidence: 80+ for strong match, 50 for weak.

    Strategy:
    1. Check keyword-based rules (highest priority)
    2. If no match, check for medical terminology
    3. Default to CLINICAL_NOTE if medical content detected (instead of OTHER)
    """
    header_lower = _header_text(page.text, max_lines=3)
    for page_type, phrases in _HARD_HEADER_RULES:
        if any(phrase in header_lower for phrase in phrases):
            page.extensions["page_type_scores"] = {page_type.value: 100}
            page.extensions["page_type_score_margin"] = 100
            return page_type, 90

    scores = _score_page_types(page.text)
    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0].value))
    page.extensions["page_type_scores"] = {ptype.value: score for ptype, score in ranked[:4] if score > 0}

    best_type = PageType.OTHER
    best_conf = 30
    if ranked and ranked[0][1] > 0:
        best_type, best_score = ranked[0]
        second_score = ranked[1][1] if len(ranked) > 1 else 0
        clinical_score = scores.get(PageType.CLINICAL_NOTE, 0)
        rich_clinical_header = any(token in _header_text(page.text, max_lines=6) for token in ("chief complaint", "assessment", "plan:"))
        if best_type == PageType.PT_NOTE and rich_clinical_header and clinical_score >= best_score - 12:
            best_type = PageType.CLINICAL_NOTE
            best_score = clinical_score
            second_score = max(second_score, scores.get(PageType.PT_NOTE, 0))
        margin = best_score - second_score
        page.extensions["page_type_score_margin"] = margin
        if best_score >= 70 and margin >= 12:
            best_conf = min(95, 60 + (best_score // 8))
        elif best_score >= 36:
            best_conf = min(75, 45 + (best_score // 10))
        else:
            best_type = PageType.OTHER
            best_conf = 30
        if margin < 10 and best_type != PageType.OTHER:
            page.extensions["page_type_ambiguous"] = True

    # Step 2: If still classified as OTHER, check for medical terminology
    if best_type == PageType.OTHER:
        medical_matches = _MEDICAL_PATTERN.findall(page.text)
        if len(medical_matches) >= 1:
            best_type = PageType.CLINICAL_NOTE
            best_conf = 45  # Low confidence but enough to process

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
        if not page.extensions: page.extensions = {}
        page.extensions["page_type_confidence"] = confidence

        if confidence < 50:
            warnings.append(Warning(
                code="PAGE_TYPE_LOW_CONF",
                message=f"Page {page.page_number} classified as '{page_type.value}' with low confidence ({confidence})",
                page=page.page_number,
                document_id=page.source_document_id,
            ))

    return pages, warnings
