# Pass 045 — Row Key Finding Repair + Unverified Content Quarantine + Packet Integrity

## 1. System State

**Stage:** Hardening (pre-pilot output quality)
**Features allowed:** No. Bug fixes and regression fixture only.

---

## 2. Failure Class

**Primary:** Output quality — the exported PDFs contain wrong key-finding snippets, unrelated clinical content, and pass with demo/synthetic data that cannot represent real cases.

**Root causes confirmed by code inspection:**

| # | Bug | File | Line |
|---|-----|------|------|
| 1 | Key finding = `candidate_pairs[0]` — first fact on page regardless of date proximity | `timeline_pdf.py` | 2497 |
| 2 | `additional_findings_rows` are rendered in INTERNAL but the unverified items can still influence tier signals upstream (signals computed before render filter) | `timeline_pdf.py` | 2428 |
| 3 | Demo packet `batch_029_complex_prior` contains synthetic "Harry Potter / Mouse / Wizard" providers — not real clinical records | `PacketIntake/batch_029_complex_prior/packet.pdf` | — |

---

## 3. Binary Success State

- **Row key finding picks a fact whose page is within ±1 page of the event's primary citation page**, not just the first fact in the list.
- **Unverified promoted items never influence top-of-page snapshot bullets** — they are demoted to the "Additional Findings" section only.
- **Regression fixtures exist** for cross-contamination (main injury + unrelated section) with explicit expected guardrail behaviour.
- **Cloud runs use a real or realistic fixture packet**, not the synthetic demo packet.
- **Regression passes**: CASES PASS, STATIC PASS, DRIFT RUN.

---

## 4. Architectural Move

### Bug 1: Key Finding Anchor Fix

**Current code** (`timeline_pdf.py` ≈ line 2495–2501):
```python
candidate_pairs = [(f, is_verbatim) for f, is_verbatim in fact_pairs if not _is_meta_language(f)]
if candidate_pairs:
    key_finding_raw, key_is_verbatim = candidate_pairs[0]  # ← BUG: first fact, no page filter
```

**Fix:** Score candidates by page proximity to the event's primary citation page, prefer the one on the same or adjacent page:
```python
def _best_key_finding(fact_pairs, event_page: int | None):
    scored = []
    for f, is_verbatim in fact_pairs:
        if _is_meta_language(f):
            continue
        # Page proximity score: 0 = exact match, higher = farther away
        page_dist = abs(getattr(f, 'page_number', event_page or 0) - (event_page or 0)) if event_page else 999
        scored.append((page_dist, f, is_verbatim))
    if scored:
        scored.sort(key=lambda x: x[0])
        _, best_f, best_verbatim = scored[0]
        return best_f, best_verbatim
    return fact_pairs[0] if fact_pairs else ("", False)
```

### Bug 2: Unverified Context Quarantine Invariant

**Current state:** Renderer already guards `additional_findings_rows` from Snapshot (line 2418 guard — INTERNAL only).

**Gap:** Upstream pipeline does not yet assert that `promoted_items` with `alignment_status != PASS` never become `SIGNAL_TIER_DRIVER = True`. Need to check `step_renderer_manifest.py` to confirm whether those items ever set tier signals.

**Fix (pending code inspection):**
- Add `INV-Q4`: Promoted items with `alignment_status not in {None, "PASS"}` must not have `headline_eligible=True` AND drive any severity/tier signal.
- Assert in `build_renderer_manifest.py` that unverified items don't back-fill tier.

### Bug 3: Packet Validation at Intake

**Add `packet_sha_allowlist` for regression** OR add a provider plausibility check:
- If >30% of providers match a known fake-name corpus (`Mouse`, `Wizard`, `Doe`, `Smith-Test`) → flag as `SYNTHETIC_PACKET` → block production run (warn only in dev).

---

## 5. Invariants Introduced

| ID | Invariant | Enforced In |
|----|-----------|-------------|
| INV-Q4 | Key finding for a timeline row must be drawn from a fact on the same or adjacent page as the event's primary citation | `timeline_pdf.py` `_best_key_finding()` |
| INV-Q5 | Promoted items with `alignment_status != PASS` must never appear in snapshot bullets | `timeline_pdf.py` (already enforced, regression test needed) |
| INV-Q6 | Regression must include a cross-contamination fixture with expectedbehaviour assertions | `tests/fixtures/invariants/case7_cross_contamination/` |

---

## 6. Files

### Modify
| File | Change |
|------|--------|
| `apps/worker/steps/export_render/timeline_pdf.py` | Add `_best_key_finding()`, use it at line ~2497 |
| `apps/worker/steps/step_renderer_manifest.py` | Confirm/fix that unverified items cannot set tier signals |
| `scripts/run_regression.py` | Update header to Pass 045 |

### New
| File | Purpose |
|------|---------|
| `tests/fixtures/invariants/case7_cross_contamination/evidence_graph.json` | Shoulder fracture + unrelated renal calculus fixture |
| `tests/fixtures/invariants/case7_cross_contamination/fixture_manifest.json` | Expected: kidney content quarantined, only shoulder drives snapshot |
| `reference/pass_045/` | Standard pass outputs |

---

## 7. Acceptance Gates

- [ ] `_best_key_finding()` unit test: event page=12, fact on page 11 wins over fact on page 3
- [ ] `case7_cross_contamination` regression case: `FIXTURE_MANIFEST` PASS
- [ ] Full regression CASES PASS (7/7), DRIFT PASS
- [ ] Cloud run uses a real/realistic packet — not `batch_029_complex_prior`
- [ ] Real cloud output PDFs stored in `reference/pass_045/`
