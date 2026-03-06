# Pass 056 Plan - Global Robustness & Edge-Case Sweep

## Objective

Harden CiteLine against unusual but valid medical records by removing brittle date assumptions, loosening structured-text rejection heuristics, preventing page-classification keyword dominance, and converting render-time kill-switches into degradeable blockers.

## Target Outcome

The pipeline must complete on research, historic, synthetic-future, and highly structured packets without silent suppression or renderer crashes. Unusual inputs may produce warnings or `needs_review`, but they must still produce deterministic artifacts.

## Sweep Findings Driving This Pass

1. Date plausibility logic is duplicated and inconsistent.
- `packages/shared/utils/clinical_utils.py:41`
- `apps/worker/steps/events/report_quality.py:75`
- `apps/worker/steps/step06_dates.py:204`
- `apps/worker/lib/billing_extract.py:126`
- `apps/worker/lib/litigation_safe_v1.py:314`
- `apps/worker/steps/events/clinical_summary.py:34`

2. Text acquisition and garbage scoring are overfit to prose-heavy records.
- `apps/worker/steps/step02_text_acquire.py:23`
- `apps/worker/steps/step02_text_acquire.py:150`
- `apps/worker/quality/text_quality.py:123`
- `apps/worker/quality/text_quality.py:211`

3. Page classification uses a fragile priority-ordered keyword count with early exit.
- `apps/worker/steps/step03_classify.py:133`

4. Export/render code still contains crash-oriented invariants.
- `apps/worker/steps/export_render/orchestrator.py:473`
- `apps/worker/steps/export_render/timeline_pdf.py:858`
- `apps/worker/steps/export_render/timeline_pdf.py:3157`
- `apps/worker/lib/leverage_trajectory.py:65`

## Architectural Move

Introduce a shared robustness policy with four layers:

1. `date_plausibility_policy`
- Separate sentinel detection from plausibility.
- Permit historical and synthetic-future dates unless they match explicit placeholder rules.
- Replace duplicated `date_sanity()` implementations with one canonical utility plus policy parameters.

2. `structured_text_tolerance_policy`
- Replace naive alpha-numeric and non-ASCII ratios with token-shape and table-structure aware checks.
- Detect structured medical layouts as valid even when punctuation density is high.
- Add a medical short-form lexicon pass so terse clinical rows like `Na 138`, `K 4.1`, `WBC 12.4`, and `BP 132/88` are treated as valid medical signal instead of token-poor noise.

3. `page_classification_scorecard`
- Score all candidate page types instead of returning on first two-keyword hit.
- Add signal sources:
  - header/first-lines boost
  - repeated token dampening
  - section-family tie breakers
  - minimum winning margin before override
- Preserve deterministic ordering.

4. `degrade_not_crash_export_policy`
- Convert renderer/blocker invariants into:
  - machine-readable blocker codes in artifacts
  - quality gate findings
  - terminal run status downgrade to `needs_review` or `partial`
- Keep true programmer/configuration errors as exceptions; convert content-shape invariants to blocker states.

## Implementation Sequence

### Phase 1 - Canonical Date Plausibility

- Add a shared utility that distinguishes:
  - placeholder/sentinel dates
  - plausible dates
  - implausible outliers
- Refactor consumers of `date_sanity()` and year cutoffs to use the shared policy.
- Eliminate packet-era assumptions like `1990 <= year <= 2200` and `year >= 1970`.

### Phase 2 - Structured Text Tolerance

- Refactor `step02_text_acquire.py` and `apps/worker/quality/text_quality.py`.
- Replace raw alpha-numeric and non-ASCII thresholds with:
  - table punctuation allowance
  - label/value pair detection
  - columnar line repetition recognition
  - CID/OCR corruption scoring that does not penalize clean structured data
- Add short-form clinical token recognition:
  - vitals abbreviations
  - common lab analytes
  - medication dose patterns
  - shorthand result/value rows
- Ensure downstream quality and extraction steps count these rows as medical signal even when token count is low.

### Phase 3 - Classifier Robustness

- Replace early-return counting in `step03_classify.py` with a score map per `PageType`.
- Weight first 10-20 lines more heavily than body repetition.
- Add summary-preservation logic so dense lab terms do not steal a discharge/summary page when summary indicators appear in headers.

### Phase 4 - Kill-Switch Conversion

- Audit all content-driven `raise RuntimeError` and `assert` paths.
- Reclassify:
  - content blocker -> artifact flag + downgrade status
  - mediation leakage/programmer misuse -> keep hard failure
- Specific targets:
  - `ED_EXISTS_BUT_NOT_RENDERED`
  - cleanroom banned-phrase handling
  - leverage trajectory dated-event assertion

## Planned Tests

### Unit

- Future date accepted as plausible non-sentinel
- Historic date accepted as plausible non-sentinel
- Structured flowsheet text not marked garbage
- Medical short-form rows not marked garbage or low-signal
- Summary-with-labs page classified as summary/discharge
- Dense repeated lab page still classified as lab
- `ED_EXISTS_BUT_NOT_RENDERED` recorded as blocker without uncaught exception

### Integration

- MIMIC-style synthetic future-year packet completes
- Structured summary/lab hybrid packet completes
- Export blocker path returns terminal degraded status with artifacts

### Regression Coverage

- `PacketIntake/batch_029_complex_prior`
- `PacketIntake/05_minor_quick`
- at least one non-spine packet
- at least one synthetic/historic/future-dated packet

## Artifacts To Produce

- `reference/pass_056/robustness_sweep_report.md`
- `reference/pass_056/robustness_matrix.json`
- `reference/pass_056/date_policy_examples.json`
- `reference/pass_056/classifier_confusion_cases.md`

## Definition of Done

- No hardcoded modern-era date bands remain in production signal/render paths without explicit policy justification.
- Structured medical tables are no longer rejected solely for punctuation or low alpha-numeric ratios.
- Page classification is score-based and resistant to keyword flooding.
- Content-shape invariants degrade status instead of crashing the export path.
- Tests cover unusual era, unusual format, and unusual density cases.
