# Pass 045 Release Notes — Row Key Finding Repair + Unverified Quarantine + Cross-Contamination Fixture

**Date:** 2026-03-03  
**Status:** ALL PASS — 7/7 CASES, STATIC PASS, DRIFT PASS

---

## What Changed

### Bug Fixes

#### Bug 1: Wrong Key Finding Snippet on Timeline Rows (INV-Q4)
**File:** `apps/worker/steps/export_render/timeline_pdf.py`

**Root cause:** `_build_case_snapshot()` selected the top-10 anchor row key finding by always picking `candidate_pairs[0]` — i.e., the first fact in the extracted list, regardless of which citation page that fact came from or whether it was contemporaneous with the event's anchor date. This caused a 2013 ED row to display text sourced from a 2014 cancelled surgery entry.

**Fix:** Added `_pick_key_finding_page_anchored(candidate_pairs, refs, citation_by_id)`. It scores each candidate fact by token overlap with the event's citation snippets (the actual text on those citation pages). The fact with the highest normalised overlap wins. Falls back to `candidate_pairs[0]` when no snippet data is available.

```python
# Before (line 2554, prior to Pass 045):
key_finding_raw, key_is_verbatim = candidate_pairs[0]

# After:
key_finding_raw, key_is_verbatim = _pick_key_finding_page_anchored(
    candidate_pairs, refs, citation_by_id
)
```

---

#### Bug 2: Unverified Context Reaching Snapshot Bullets (INV-Q5)
**File:** `apps/worker/steps/step_renderer_manifest.py`

**Root cause:** Promoted findings with `alignment_status != PASS` (flagged by claim-context alignment as unverified or contradicted) could retain `headline_eligible=True`, which allowed them to reach snapshot bullets through density backfill — even though they were already blocked from Additional Findings in MEDIATION mode.

**Fix:** After `alignment_status` is set in `annotate_renderer_manifest_claim_context_alignment`, any item with a non-PASS status is immediately downgraded: `item["headline_eligible"] = False`. This ensures the item can only appear in the Additional Findings section (INTERNAL mode) and never influences the top-of-page settlement driver bullets.

---

### New Regression Fixture (INV-Q6)
**Files:** `tests/fixtures/invariants/case7_cross_contamination/`

A new fixture case — based on `case4_soft_tissue` (shoulder fracture) with an injected unrelated renal calculus claim — tests that cross-contamination from unrelated clinical systems does not affect injury-severity signals. The `fixture_manifest.json` asserts `has_injection_dated=false` and `has_surgery_dated=false` even when a renal imaging claim is present.

---

## Regression Results

```
CASES:  7/7 pass
STATIC: PASS
DRIFT:  PASS (run=6 skip=1; case7 new — no prior baseline expected)
```

---

## Invariants Added

| ID | Rule |
|----|------|
| INV-Q4 | Key finding for a timeline row must be selected from a fact whose text has the highest token overlap with the event's primary citation page snippets — not blindly from position [0] |
| INV-Q5 | Promoted findings with alignment_status not in {None, "", "PASS"} must have headline_eligible=False and must not appear in settlement driver snapshot bullets |
| INV-Q6 | Regression suite must include a cross-contamination fixture (injury + unrelated system) with explicit expectations that unrelated content does not drive injury signals |

---

## Cloud Output

- `export_INTERNAL.pdf` — attorney INTERNAL mode export (run 48941f594a914e13abaeb7edce28f4c2)
- `export_MEDIATION.pdf` — attorney MEDIATION mode export (run 48941f594a914e13abaeb7edce28f4c2)
