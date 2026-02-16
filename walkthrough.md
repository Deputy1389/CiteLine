# CiteLine Full Extraction Evaluation Report

**Date:** 2026-02-15  
**Corpus:** `C:\CiteLine\testdata\` (11 PDFs)  
**Pipeline Version:** 0.1.0 (deterministic, rule-based)

---

## Step 1 — Prerequisites ✅

| Component | Status |
|-----------|--------|
| API (`uvicorn apps.api.main:app --port 8000`) | Running (6+ hours) |
| Worker (`python -m apps.worker.runner`) | Running (5+ hours) |
| OCR (Tesseract) | **Not installed** — embedded text only |

---

## Step 2 — Batch Ingestion ✅

- Script: `python scripts/batch_ingest.py`
- **Exit code: 0** — no crashes
- All 11 files processed with isolated Matters (1 Matter per file)
- Results saved: [summary.json](file:///C:/CiteLine/data/batch_runs/summary.json)

---

## Step 3 — Artifact Validation ✅

Every run produced all 3 required artifacts:

| Run ID | chronology.pdf | chronology.csv | evidence_graph.json |
|--------|:-:|:-:|:-:|
| All 11 runs | ✅ | ✅ | ✅ |

> All files are non-empty. Evidence graphs contain full page text, provider data, and warning metadata.

---

## Step 4 — Per-Document Extraction Quality

| File | Pages | Events | Providers | Gaps | Status | Issues |
|------|:-----:|:------:|:---------:|:----:|--------|--------|
| **eval_01_amfs_packet.pdf** | 172 | 18 | 34 | 0 | partial | 27 MISSING_DATE warnings, 3 OCR_UNAVAILABLE, 32 PAGE_TYPE_LOW_CONF |
| **eval_02_millie_day1.pdf** | 12 | 0 | 1 | 0 | partial | 4 MISSING_DATE — uses relative dates ("Day 1") |
| **eval_03_millie_day2.pdf** | 12 | 0 | 1 | 0 | partial | Same relative date issue as eval_02 |
| **eval_04_millie_day3.pdf** | 11 | 0 | 1 | 0 | partial | Same relative date issue |
| **eval_05_millie_day4.pdf** | 10 | 0 | 1 | 0 | partial | Same relative date issue |
| **eval_06_julia_day1.pdf** | 12 | 0 | 1 | 0 | partial | Same relative date issue |
| **eval_07_julia_day2.pdf** | 13 | 0 | 1 | 0 | partial | Same relative date issue |
| **eval_08_julia_day3.pdf** | 12 | 0 | 1 | 0 | partial | Same relative date issue |
| **eval_09_head_ct_report.pdf** | 4 | 0 | 4 | 0 | success | Educational guide, not real report — no impression section to extract |
| **eval_10_brain_mri_report.pdf** | 4 | 0 | 5 | 0 | success | Educational guide — same issue as eval_09 |
| **sample-medical-chronology172.pdf** | 172 | 18 | 34 | 0 | partial | **Duplicate of eval_01** (identical SHA256) |

---

## Step 5 — Aggregate Summary

| Metric | Value |
|--------|-------|
| **Total PDFs processed** | 11 (10 unique) |
| **Total pages processed** | 434 |
| **Total events extracted** | 36 (18 unique — eval_01 = sample-chronology172) |
| **Average events per document** | 3.3 (or **1.8 unique**) |
| **Failed runs** | 0 |
| **Runs with 0 events** | 9 of 11 (82%) |
| **Runs with missing providers** | 0 (providers detected in all) |

> [!WARNING]
> **82% of documents produced zero events.** This is a critical extraction quality issue, not a stability issue. The pipeline is stable but overly conservative.

---

## Step 6 — Extraction Improvement Opportunities (Diagnosis Only)

### 🔴 Critical: Date Extraction (Root Cause of 82% Zero-Event Rate)

**Problem:** The nursing simulation PDFs (eval_02 through eval_08) use **relative dates** like "Day 1, 0900" and "Day 2" instead of absolute dates (e.g., "01/15/2026"). The date extractor (`step06_dates.py`) only matches standard date formats via regex.

**Impact:** Every clinical event group gets a `MISSING_DATE` warning and is skipped entirely. For `eval_01` (172 pages), 27 event groups were skipped — meaning potentially **45+ events were lost** because the date extractor couldn't find valid dates on those pages.

**Specific gaps:**
- No support for relative/contextual dates ("Day 1", "Day 2", "0200", "0900")
- No date propagation from header/admission date to subsequent pages
- No fallback to document-level dates (e.g., admission date from page 1)

### 🟡 Major: Provider Detection (High False Positive Rate)

**Problem:** Provider detection uses broad keyword matching that captures generic text as provider names.

**Evidence from eval_09 (Head CT guide):**
- Detected: `"Your healthcare provider (usually a doctor, nurse practitioner, or"` → Classified as ER provider
- Detected: `"and treat diseases. A radiologist (http://www.radiologyinfo.org) is a"` → Classified as ER provider
- Detected: `"medical terminology and complex information. If you have any"` → Classified as ER provider

**Evidence from eval_02 (nursing notes):**
- Detected: `"Intravenous Therapy"` as a provider (it's a section heading)
- Missed actual providers: Dr. Eric Lund, Jean Larsen RN, Kathy Clark RN

**Impact:** Provider count is inflated (eval_09 shows 4 "providers" that are actually sentence fragments), while real named providers are missed.

### 🟡 Major: Imaging Extraction (Zero Events Despite Correct Classification)

**Problem:** `eval_09` (Head CT) and `eval_10` (Brain MRI) are correctly classified as `imaging_report` pages but produce zero events.

**Root causes:**
1. **Date extraction failure** — The imaging extractor requires `page_dates` to be non-empty, but the date extractor didn't find standard date patterns in the educational text (dates like "July 16th, 2024" exist but use ordinal format `16th` which may not match the regex)
2. **Impression section requirement** — The extractor requires "Impression" or "Findings" sections. The educational guide has "Example:" sections that describe impressions but don't match the exact heading format

### 🟢 Good: Multi-Page Event Grouping

**Working correctly.** In `eval_01`, the grouping logic successfully merged multi-page clinical notes:
- Pages [34, 35, 36] grouped as single event
- Pages [60–68] (9 pages) grouped as single event
- Pages [156–162] (7 pages) grouped as single event

The grouping algorithm correctly uses document ID continuity, page number contiguity, and date/provider compatibility.

### 🟢 Good: Page Type Classification (Mostly Accurate)

**Working reasonably.** Even with no OCR:
- Nursing notes correctly classified as `clinical_note`
- Imaging reports correctly classified as `imaging_report`
- Billing pages correctly classified as `billing`
- I&O worksheets appropriately classified as `other` or `billing`

**Issues:** 32 pages in eval_01 classified as `other` with low confidence (30) — these may be valid clinical pages that lack enough keyword signals.

### 🟡 Moderate: Chronology Ordering

**Cannot fully evaluate** with current data since only 18 events were extracted across 172 pages. With so few events, the chronology is sparse. Need more events extracted to properly assess ordering quality.

---

## Production Readiness Assessment

### Verdict: **NOT production-ready** for real personal injury medical records

| Capability | Grade | Notes |
|-----------|:-----:|-------|
| **Pipeline Stability** | A | No crashes, handles all file types |
| **Artifact Generation** | A | PDF, CSV, JSON exports reliably produced |
| **Date Extraction** | F | Fails on relative dates, ordinal dates, contextual dates |
| **Provider Detection** | D | High false positive rate, misses named providers |
| **Event Recall** | F | 82% of files produce zero events |
| **Imaging Extraction** | D | Correct classification but zero event yield |
| **Multi-Page Grouping** | B+ | Works well when dates are present |
| **Page Classification** | B | Mostly accurate, some low-confidence misses |

### Priority Improvements (No Code Changes Yet)

1. **P0 — Date extraction overhaul**: Support relative dates, ordinal dates (`16th`), date propagation from headers/admission, and document-level fallback dates
2. **P1 — Provider detection precision**: Require name-like patterns (Title + Last Name, or credential suffixes like MD/RN/DO), filter out sentence fragments
3. **P2 — Imaging extractor flexibility**: Handle ordinal date formats, relaxed section heading matching
4. **P3 — Confidence threshold tuning**: The `event_confidence_min_export: 60` setting excluded 1 of 18 events from eval_01; review if threshold is appropriate
