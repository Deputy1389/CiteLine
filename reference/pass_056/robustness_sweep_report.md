# Pass 056 Robustness Sweep Report

## Scope

This report inventories code paths that are brittle against unusual but valid medical data. It focuses on:

- hardcoded sanity limits
- page classification heuristics
- kill-switch invariants
- text acquisition and garbage thresholds

## Summary

The dominant failure mode is not malformed data. It is valid data that violates unspoken assumptions:

- dates must look modern
- medical text must look prose-like
- medical signal must be verbose enough to look like natural language
- page types must be obvious from raw keyword counts
- render blockers may terminate the export instead of degrading status

## Findings

| Category | Fragile File | Specific Line(s) | Current Fragility | Recommended Robust Refactor |
|---|---|---|---|---|
| Date range | `packages/shared/utils/clinical_utils.py` | `41-43` | `date_sanity()` rejects any year after `date.today().year`, which breaks future-dated synthetic or research packets and rejects valid historic-but-non-placeholder material below 1902. | Replace with canonical `is_placeholder_date()` plus `is_plausible_date(policy)`; permit configurable historical and forward offsets instead of tying validity to wall-clock year. |
| Duplicate date gate | `apps/worker/steps/events/report_quality.py` | `75-81` | Duplicates the same modern-only year logic in a second location, guaranteeing drift. | Delete duplicate policy and import the shared date plausibility utility. |
| Date parser band | `apps/worker/steps/step06_dates.py` | `204-205` | Parsed dates outside `1990 <= year <= 2200` are silently discarded, which is too narrow for historic records and still arbitrary for synthetic data. | Centralize date plausibility bounds and return parsed outlier dates with a warning classification instead of dropping them. |
| Billing date band | `apps/worker/lib/billing_extract.py` | `123-127` | Billing dates outside `1900 <= year <= 2100` are discarded; two-digit year expansion always assumes 2000s. | Reuse the shared date plausibility policy and make two-digit year expansion policy-driven based on neighboring context. |
| Summary date suppression | `apps/worker/steps/events/clinical_summary.py` | `34-35`, `109-110` | Summary/treatment-phase logic ignores all dates before 1970, which drops valid historical records and synthetic fixtures. | Replace `year >= 1970` with shared non-placeholder plausibility. |
| Gap calculation cutoff | `apps/worker/lib/litigation_safe_v1.py` | `314-315` | Gap analysis skips any treatment event before 2000. This can erase valid care windows entirely on older or synthetic datasets. | Use sentinel-aware plausibility, not a millennium cutoff. Preserve older dates and annotate if outlier policy triggers. |
| Text meaningfulness length floor | `apps/worker/steps/step02_text_acquire.py` | `23`, `52-64` | Embedded text under 50 chars is treated as non-meaningful even if it is a dense table header or concise structured summary. | Replace absolute length with signal-aware checks: label/value pairs, table rows, medically dense short forms, and repeated structured fields. |
| OCR trigger density | `apps/worker/steps/step02_text_acquire.py` | `91-95` | Any page with `0 < non_ws < 200` is forced into OCR, which is too aggressive for structured one-page summaries and sparse but valid result pages. | Make OCR triggering depend on font-layer quality plus structured-text validity, not just character count. |
| OCR quality warning ratios | `apps/worker/steps/step02_text_acquire.py` | `150-160` | `non_ascii > 0.2` and `alpha_num ratio < 0.2` flags pages that are clean but punctuation-heavy, table-heavy, or symbol-heavy. | Replace with token-shape features: proportion of label/value rows, repeated delimiters, CID artifacts, and low-entropy corruption signals. |
| Tokenization bias against short-form clinical rows | `apps/worker/quality/text_quality.py` | `120-128`, `139-142`, `240-278` | The quality pipeline assumes medical signal is verbose. Rows like `Na 138`, `K 4.1`, `WBC 12.4`, `BP 132/88` can look too short, too symbolic, or too low-density and be misclassified as garbage or weak signal. | Add a medical short-form lexicon and value-pattern recognizer before prose heuristics. Treat common analyte/vitals/result rows as positive medical signal even when token count is low. |
| Garbage score minimum token count | `apps/worker/quality/text_quality.py` | `123-128` | `quality_score()` returns `0.0` for fewer than four tokens, unfairly punishing short but valid structured lines. | Score short text using medical token presence, numeric/value pairs, and delimiter-aware patterns instead of dropping to zero. |
| Garbage flags by density/diversity | `apps/worker/quality/text_quality.py` | `139-142`, `253-278` | Medical density and diversity thresholds are prose-biased and can label valid structured content as garbage. | Add a structured-text branch before prose heuristics; if the text matches table/flowsheet morphology, score it separately. |
| Whole-block garbage threshold | `apps/worker/quality/text_quality.py` | `205-213` | If more than 40% of lines are “garbage,” the whole block is rejected. Structured records with abbreviations or value rows can cross that threshold easily. | Weight lines by medical/value content and permit high delimiter density when rows are consistent and parseable. |
| Classifier early-return dominance | `apps/worker/steps/step03_classify.py` | `133-146` | The classifier returns immediately on the first type with two keyword hits. A summary page with many embedded lab terms can be stolen by `LAB_REPORT` before stronger summary cues are evaluated globally. | Score all page types, then choose the winner by weighted score and winning margin. No early return except for explicit header-level hard matches. |
| Classifier weak fallback | `apps/worker/steps/step03_classify.py` | `148-155` | Any page with one generic medical match becomes `CLINICAL_NOTE`, which hides uncertainty and collapses nuanced page families. | Add an explicit `MIXED_CLINICAL` or retain `OTHER` with evidence scores in extensions when the winning margin is low. |
| Render blocker invariant | `apps/worker/steps/export_render/timeline_pdf.py` | `3157-3158` | `ED_EXISTS_BUT_NOT_RENDERED` raises `RuntimeError`, terminating export instead of finishing with a machine-readable blocker. | Move this to pipeline/orchestrator status mapping: emit blocker code, attach invariant artifact, degrade to `needs_review`, still persist artifacts where safe. |
| Cleanroom phrase blocker | `apps/worker/steps/export_render/timeline_pdf.py` | `856-858` | Banned-phrase detection raises immediately, which can turn one leakage bug into total export failure with no useful artifact trail. | Record the banned phrase finding in `quality_gate` and fail closed at status level; optionally write a stub PDF cover page rather than crash. |
| Recursive mediation field blocker | `apps/worker/steps/export_render/timeline_pdf.py` | `873-885` | Any banned field in the render payload triggers `RuntimeError` during traversal. | Convert content leakage to structured blocker output unless it is a programmer misuse in development-only paths. |
| Orchestrator mediation payload blocker | `apps/worker/steps/export_render/orchestrator.py` | `469-485` | Non-extension mediation payload keys and settlement leakage raise immediately instead of being handled through the same quality-gate framework. | Preserve hard failure for explicit programmer/config misuse in dev, but in production runs convert payload leakage into blocker artifacts and degraded terminal status. |
| Assertion-based kill switch | `apps/worker/lib/leverage_trajectory.py` | `63-65` | An `assert` on dated escalation events can crash optimized or production flows unpredictably and is not user-safe. | Replace with explicit validation that drops invalid events, records invariant violations, and continues with reduced coverage. |

## Page Classification Refactor Proposal

The current classifier in `apps/worker/steps/step03_classify.py` is priority ordered and return-based. That makes it vulnerable to keyword flooding.

### Recommended scoring model

1. Score every `PageType` independently.
- `header_score`: matches in first 10-20 lines
- `body_score`: total normalized keyword hits
- `rarity_bonus`: high-information phrases like `discharge summary`, `operative findings`
- `repetition_dampener`: repeated lab tokens should stop compounding indefinitely

2. Add dominance rules.
- If a top-of-page header contains a high-confidence summary label, labs/imaging keywords in the body must exceed it by a configurable margin to steal the page.

3. Persist the scorecard.
- Store the top candidate scores in `page.extensions["page_type_scores"]` for debugging and regression review.

4. Resolve low-margin ties explicitly.
- If the winning margin is below threshold, emit `PAGE_TYPE_AMBIGUOUS` and choose the least-destructive downstream type.

## Kill-Switch Conversion Rules

Not every `raise` should be removed. The split should be:

- Keep hard failures:
  - missing required config
  - API boot/auth misconfiguration
  - programmer misuse that would leak forbidden data across trust boundaries

- Convert to degradeable blockers:
  - content-shape mismatches
  - required bucket/render parity gaps
  - cleanroom leakage found inside produced content
  - undated/invalid derived items in downstream feature packs

## Recommended First Implementation Order

1. Canonical date plausibility utility and call-site replacement
2. Structured-text tolerance plus medical short-form lexicon in `step02_text_acquire.py` and `apps/worker/quality/text_quality.py`
3. Weighted page classification scorecard in `step03_classify.py`
4. Conversion of content-driven render `RuntimeError` paths into blocker artifacts plus status downgrade

## Additional Robustness Note: Tokenization Bias

Structured medical data frequently encodes core clinical signal in compact rows rather than narrative sentences. Examples:

- `Na 138`
- `K 4.1`
- `WBC 12.4`
- `BP 132/88`

These rows are medically rich but token-poor. In the current pipeline, they are at risk because quality logic rewards:

- higher token counts
- prose-like medical density
- diversity patterns that resemble sentences

Recommended mitigation:

1. Add a short-form lexicon for:
- common labs
- vitals
- measurement abbreviations
- medication-dose rows

2. Add value-pattern detection:
- analyte plus numeric value
- vital plus slash-delimited or decimal measurement
- abbreviation plus units

3. Run this detection before garbage scoring and confidence suppression.

4. Thread a boolean like `structured_medical_signal=true` into downstream quality/extraction scoring so short-form rows are not treated as weak evidence by default.

## Pass 056 Deliverables

- `reference/pass_056/checklist056.md`
- `reference/pass_056/plan.md`
- `reference/pass_056/robustness_sweep_report.md`
