# PI Chronology MVP — Deterministic Extraction Pipeline (v0.1)

Design goals (production-level):
- **Citation-first**: no exported fact without stored citation snippet + bbox.
- **Deterministic core**: rules/heuristics are stable and testable; any LLM usage must be optional and never the only path.
- **Auditable artifacts**: preserve original page numbering; render exports from structured events.
- **ClearCase learnings applied**: track every run (RUN_RECORD), store extraction receipts, and prefer traceability over “smart” prose.
- **Safety / UPL posture**: extract objective facts only; no advice, no valuation, no demand drafting.

---

## Step 0 — Inputs validation
1. Verify each SourceDocument:
   - mime_type == application/pdf
   - sha256 is present and unique per document
   - bytes > 0
2. Enforce run_config.max_pages:
   - If exceeded, return status=partial with warning code=MAX_PAGES_EXCEEDED; process first N pages deterministically.

Outputs:
- RunRecord.started_at
- Metrics.documents

---

## Step 1 — PDF page split + numbering
1. Split each PDF into page images (for OCR) and extract embedded text layer if present.
2. Assign global `page_number` starting at 1 across all uploaded PDFs in upload order.
3. Record Page objects:
   - page_number
   - text_source = embedded_pdf_text if extractable else ocr (later filled)
   - layout dimensions if available

Outputs:
- EvidenceGraph.pages (skeleton)
- Metrics.pages_total

---

## Step 2 — Text acquisition (embedded text first, OCR fallback)
For each page:
1. If embedded text is non-trivial (length >= 50 chars and not mostly whitespace), keep it.
2. Else run OCR once and store `text_source = ocr`.

Hard rule:
- Do not run OCR twice on same page (idempotent).

Outputs:
- Page.text
- Metrics.pages_ocr

---

## Step 3 — Page type classification (rule-based)
For each page, assign Page.page_type using high-precision keyword heuristics:

Priority order:
1. operative_report: ("operative report", "procedure", "anesthesia", "pre-op", "post-op")
2. imaging_report: ("impression", "findings", "technique", "radiology", "mri", "ct", "x-ray", "ultrasound")
3. billing: ("statement", "charges", "balance", "total due", "cpt", "hcfa", "ub-04", "invoice", "ledger")
4. pt_note: ("physical therapy", "pt daily note", "exercise", "plan of care", "visit #")
5. discharge/admission captured later by encounter logic but keep as clinical_note unless strong admin markers
6. administrative: ("fax cover", "authorization", "release of information", "roi", "request", "records sent")
7. clinical_note: ("chief complaint", "history of present illness", "assessment", "plan", "ros", "physical exam")
8. other

Store spans into Document.page_types after step 4.

Outputs:
- Page.page_type
- Warnings for low-confidence classification (PAGE_TYPE_LOW_CONF)

---

## Step 4 — Document segmentation
Goal: create Document objects that represent contiguous runs of similar content.
1. Group pages by source_document_id and detect section breaks by:
   - sudden page_type changes
   - repeated headers/footers shifting
2. Emit Document records with:
   - page_start/page_end
   - page_types spans
   - declared_document_type inferred from dominant page_type:
     - billing -> medical_bill
     - clinical/imaging/operative/pt -> medical_record
     - administrative/other -> unknown (or correspondence if letter patterns appear)

Outputs:
- EvidenceGraph.documents

---

## Step 5 — Provider detection + normalization
For each Document and its pages:
1. Detect provider candidates via patterns:
   - letterhead blocks (top 20% of page)
   - lines like "Facility:", "Provider:", "Rendering Provider", "Attending", "Radiology"
2. Choose provider per Document:
   - prefer facility/clinic over individual physician for provider_id
3. Normalize:
   - lower, strip punctuation
   - remove suffixes (llc, inc, medical group)
   - standardize common variants (saint/st., center/ctr)
   - fuzzy cluster within case (e.g., token set similarity) with deterministic threshold

Emit Provider objects and link Document.provider_id when confidence >= threshold.

Outputs:
- EvidenceGraph.providers
- Metrics.providers_total
- ProviderEvidence (snippet + bbox) for auditability

---

## Step 6 — Date extraction (tiered)
For each candidate event page-set:
1. Extract Tier 1 dates by explicit labels:
   - "date of service", "dos", "encounter date", "visit date"
   - imaging: "exam date", "study date"
   - admission: "admit date"; discharge: "discharge date"
2. Tier 2 dates:
   - header date near patient info
   - "seen on" patterns
3. Reject:
   - "printed on", "generated on", "faxed on" unless page_type is administrative and event_type is administrative.

If multiple dates compete:
- Imaging: prefer exam/study date over report date.
- Billing: statement date is BillingDetails.statement_date; service range stored separately.

Outputs:
- Candidate EventDate with source tier

---

## Step 7 — Event extraction by page type (deterministic rules)

### 7A Clinical note events
Create one Event per (provider, resolved encounter date) for a contiguous note section.

Encounter type rules:
- er_visit if ER/ED markers present (e.g., "Emergency Department", "ED Provider Note", "Triage")
- hospital_discharge if "Discharge Summary" or "Discharged" markers
- hospital_admission if "Admitted" markers and not discharge
- procedure if operative_report
- office_visit default for clinical_note

Content anchors (require ≥1):
- "Chief Complaint"
- "Assessment" or "Diagnosis"
- "Plan"
- "Procedure"
- "Work status" / "restrictions"

Facts extraction:
- Extract 3–6 bullet facts max:
  - chief complaint line (if present)
  - 1–3 assessment/diagnosis items
  - 1–2 plan items
  - restrictions/off-work statement if present
Each fact must reference a stored Citation.

### 7B Imaging events
Create Event if:
- modality detected AND (Impression OR Findings section present) AND exam/study date resolved.
Extract:
- modality + body_part
- up to 3 impression bullets (verbatim preferred)

### 7C PT events
Default aggregate mode:
- bucket events per provider by run_config.pt_aggregate_window_days
- facts include "sessions documented: N" plus up to 2 progress statements if explicit

Per-visit mode:
- only if each visit note has explicit visit date label; otherwise fall back to aggregate with warning PT_PER_VISIT_FALLBACK.

### 7D Billing events (always stored; export optional)
Create Event if:
- statement date OR service date range found AND total amount found OR line items found.
Store BillingDetails:
- statement_date
- service_date_range (if present)
- total_amount
- line_item_count
- has_cpt_codes / has_icd_codes flags

Outputs:
- EvidenceGraph.events
- EvidenceGraph.citations

---

## Step 8 — Citation capture (snippet + bbox)
For every extracted Fact, ProviderEvidence, and key date selection:
1. Capture Citation:
   - source_document_id
   - page_number
   - snippet (<= 500 chars)
   - bbox (x,y,w,h) in page coordinate system
2. Hash snippet for integrity (text_hash).

Hard rule:
- If bbox cannot be determined, set bbox to the line-level bounding box or whole-page region with warning BBOX_FALLBACK.

Outputs:
- EvidenceGraph.citations

---

## Step 9 — De-duplication + merge
1. Merge Events with same (provider_id, event_type, date) when:
   - pages are contiguous OR overlap in citations
2. Cap facts:
   - facts max 10 (prefer higher-confidence facts)
3. Keep all citations (for audit).

Outputs:
- Cleaned EvidenceGraph.events

---

## Step 10 — Confidence scoring + flags
Compute Event.confidence (0–100):
- Date tier1 +40, tier2 +25
- Provider tier1 +30, tier2 +15
- Encounter type strong cue +20
- Content anchor present +10
- Conflicts -25

Flags:
- LOW_CONFIDENCE if confidence < run_config.event_confidence_min_export
- MULTIPLE_DATE_CONFLICT, PROVIDER_UNCERTAIN, PAGE_TYPE_UNCERTAIN

Apply export rule:
- exclude or include-with-flag based on run_config.low_confidence_event_behavior

Outputs:
- Event.confidence, flags
- Metrics.events_total

---

## Step 11 — Chronology ordering + gap detection
1. Sort exported events by date.
2. Compute gaps between adjacent non-billing events:
   - if delta_days >= run_config.gap_threshold_days -> emit Gap object
3. Link Gap.related_event_ids (prev and next).

Outputs:
- EvidenceGraph.gaps

---

## Step 12 — Export rendering (PDF + CSV + optional JSON)
PDF:
- Title page with run id + disclaimer: "Factual extraction with citations. Requires human review."
- Timeline table:
  - Date, Provider, Type, Facts, Page refs
- Appendix (optional):
  - Gap list

CSV:
- One row per Event with flattened fields:
  - event_id, date, provider, type, confidence, facts_joined, pages

JSON:
- Full object adhering to schema (recommended for internal use + future Audit add-on)

Outputs:
- ChronologyOutput.exports with sha256 + bytes

---

## Step 13 — Run receipts + retention
1. Persist RunRecord with:
   - metrics, warnings, provenance (pipeline version, ocr engine version)
2. Store inputs/outputs hashes for audit.
3. Apply retention policy:
   - delete page images after retention window if configured; keep structured outputs and minimal citations per firm policy.

Outputs:
- outputs.run (RUN_RECORD)
