from enum import Enum


class PageType(str, Enum):
    CLINICAL_NOTE = "clinical_note"
    OPERATIVE_REPORT = "operative_report"
    IMAGING_REPORT = "imaging_report"
    PT_NOTE = "pt_note"
    BILLING = "billing"
    ADMINISTRATIVE = "administrative"
    LAB_REPORT = "lab_report"
    DISCHARGE_SUMMARY = "discharge_summary"
    OTHER = "other"


class EventType(str, Enum):
    OFFICE_VISIT = "office_visit"  # Was CLINICAL_VISIT
    PT_VISIT = "pt_visit"
    IMAGING_STUDY = "imaging_study"  # Was IMAGING_EVENT
    PROCEDURE = "procedure"
    LAB_RESULT = "lab_result"
    DISCHARGE = "discharge"
    BILLING_EVENT = "billing_event"
    ER_VISIT = "er_visit"
    HOSPITAL_ADMISSION = "hospital_admission"
    HOSPITAL_DISCHARGE = "hospital_discharge"
    INPATIENT_DAILY_NOTE = "inpatient_daily_note"
    WORK_STATUS = "work_status"
    ADMINISTRATIVE = "administrative"
    REFERENCED_PRIOR_EVENT = "referenced_prior_event"
    OTHER_EVENT = "other_event"


class DateSource(str, Enum):
    TIER1 = "tier1"  # Explicit label (e.g. "Date of Service")
    TIER2 = "tier2"  # Contextual/Header date
    PROPAGATED = "propagated"  # Inherited from previous page in same document
    ANCHOR = "anchor"  # Derived from anchor date + relative offset (e.g. "Day 2")


class DateKind(str, Enum):
    SINGLE = "single"
    RANGE = "range"


class ProviderType(str, Enum):
    PHYSICIAN = "physician"
    HOSPITAL = "hospital"
    IMAGING = "imaging"
    PT = "pt"
    ER = "er"
    PCP = "pcp"
    SPECIALIST = "specialist"
    UNKNOWN = "unknown"


class ClaimType(str, Enum):
    INJURY_DX = "INJURY_DX"
    SYMPTOM = "SYMPTOM"
    IMAGING_FINDING = "IMAGING_FINDING"
    PROCEDURE = "PROCEDURE"
    MEDICATION_CHANGE = "MEDICATION_CHANGE"
    WORK_RESTRICTION = "WORK_RESTRICTION"
    TREATMENT_VISIT = "TREATMENT_VISIT"
    GAP_IN_CARE = "GAP_IN_CARE"
    PRE_EXISTING_MENTION = "PRE_EXISTING_MENTION"


class FactKind(str, Enum):
    CHIEF_COMPLAINT = "chief_complaint"
    ASSESSMENT = "assessment"
    PLAN = "plan"
    DIAGNOSIS = "diagnosis"
    MEDICATION = "medication"
    IMPRESSION = "impression"
    FINDING = "finding"
    PROCEDURE_NOTE = "procedure_note"
    BILLING_ITEM = "billing_item"
    RESTRICTION = "restriction"
    LAB = "lab"
    PROCEDURE = "procedure"
    PROVIDER = "provider"
    ROM_VALUE = "rom_value"
    STRENGTH_GRADE = "strength_grade"
    PAIN_SCORE = "pain_score"
    NEURO_SYMPTOM = "neuro_symptom"
    OTHER = "other"


class ImagingModality(str, Enum):
    MRI = "mri"
    CT = "ct"
    XRAY = "xray"
    ULTRASOUND = "ultrasound"
    OTHER = "other"


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class DocumentType(str, Enum):
    PDF = "pdf"
    PNG = "png"
    JPEG = "jpeg"
    MEDICAL_RECORD = "medical_record"
    MEDICAL_BILL = "medical_bill"
    UNKNOWN = "unknown"
