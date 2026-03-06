# Pass 067 - Rasterized OCR Timeout Mitigation

## 1. System State

**Stage**: Hardening -> early Productization

**Signal layer status**: Narrow-pilot ready on validated text-backed packets; broad launch still blocked by rasterized OCR timeout behavior

**Leverage layer status**: Not relevant to this pass

**Are we allowed to add features this pass?** No

**If yes, why is this safer than further hardening?**

Not applicable. This is a hardening pass against a remaining launch blocker.

**Active stage constraints:**

- Do not lower quality gates just to mark rasterized scans as successful
- Keep OCR fallback deterministic
- Preserve existing embedded-text and noisy-OCR behavior
- Fix timeout collapse, not the review policy around extracted content

---

## 2. Failure Class Targeted

This pass must eliminate or reduce exactly ONE primary failure class:

- [ ] Data integrity failure
- [ ] Narrative inconsistency
- [ ] Required bucket miss
- [ ] Determinism variance
- [ ] Export leakage
- [ ] Signal distortion
- [ ] Trust erosion risk
- [ ] Review burden inflation
- [x] Performance bottleneck
- [ ] Architectural coupling / layer bleed

**Which one is primary?**

Performance bottleneck

**Optional secondary (only if tightly related):**

Signal distortion

**Why is this the highest risk right now?**

Pass 66 showed broad launch is still blocked by a live-worker OCR timeout on fully rasterized compact scans. The packet does not crash, but extraction collapses to zero events because whole-page OCR times out on 4/5 pages.

---

## 3. Define the Failure Precisely

**What test fails today?**

A fully rasterized compact scan can hit full-page Tesseract timeouts and return `OCR_NO_TEXT`, leaving the packet with effectively no usable chronology extraction.

**What artifact proves the issue?**

- `reference/pass_063/summary.json`
- `reference/pass_066/launch_acceptance_matrix.json`

Specifically: `packet_mimic_10002930_rasterized_clean.pdf` -> `pages_ocr=1`, `events_total=0`.

**Is this reproducible across packets?**

Yes for the currently validated rasterized compact packet class.

**Is this systemic or packet-specific?**

Systemic within the current OCR strategy because the failure mode is whole-page timeout, not a unique packet parser bug.

---

## 4. Define the Binary Success State

After this pass, the following must be true:

**Must be impossible:**

- A page that times out at whole-page OCR must not immediately collapse to empty text if deterministic tiled OCR fallback can still recover text.

**Must be guaranteed:**

- `_ocr_page()` retries with a tiled fallback after whole-page OCR timeouts.
- Tiled OCR combines non-empty segments deterministically in reading order.

**Must pass deterministically:**

- For the same page image and mocked timeout pattern, `_ocr_page()` returns the same recovered text.

---

## 5. Architectural Move (Not Patch)

This pass makes the following architectural move(s):

- [x] Adding boundary enforcement?
- [x] Introducing a guard pattern?
- [ ] Consolidating logic?
- [ ] Eliminating duplication?
- [ ] Separating layers more cleanly?

**Describe the move:**

Add a structured OCR fallback ladder: whole-page OCR first, then deterministic tiled OCR on timeout. That changes OCR from single-shot failure to bounded recovery without changing downstream extraction semantics.

---

## 6. Invariant Introduced or Strengthened

**Invariant ID**: INV-OV2

**Name**: OCR_TIMEOUT_MUST_ATTEMPT_TILED_FALLBACK

**What must always be true after this pass?**

When whole-page OCR times out, the OCR path must attempt deterministic tiled recovery before returning empty text.

**Where is it enforced?**

`apps/worker/steps/step02_text_acquire.py` :: `_ocr_page()`

**Where is it tested?**

`tests/unit/test_ocr_acquire_text.py`

**What is added to `governance/invariants.md`?**

A pass-67 registry entry for `INV-OV2`.

---

## 7. Tests Added

**Unit tests:**

- `tests/unit/test_ocr_acquire_text.py :: test_ocr_page_uses_tiled_fallback_after_full_page_timeouts` - asserts tiled recovery path returns text after full-page timeouts

**Integration tests (if any):**

- cloud rerun of the rasterized compact packet

**Determinism comparison (if applicable):**

- tiled segment ordering remains top-to-bottom and deterministic

**Artifact-level assertion (if applicable):**

- `reference/pass_067/summary.json` must show the rasterized validation packet with more than zero OCR-recovered content if the fix works

**If no new test is added, justify why:**

Not applicable

**Total new tests:** 1

---

## 8. Risk Reduced

This pass reduces which risks:

- [x] Legal risk
- [x] Trust risk
- [x] Variability
- [ ] Maintenance cost
- [x] Manual review time

**Explain how each checked risk is reduced:**

- Legal risk: reduces empty/garbled OCR output on scanned packets.
- Trust risk: avoids a false impression that the system cannot handle simple rasterized scans.
- Variability: makes timeout handling explicit and repeatable.
- Manual review time: increases the chance that scanned packets arrive with usable chronology structure instead of blank extraction.

---

## 9. Overfitting Check

**Is this solution generalizable?**

Yes. It targets timeout recovery on rasterized scans as a class.

**Does it depend on a specific test packet?**

No, though it is validated first against the current rasterized MIMIC packet.

**Could this break other case types?**

Low risk if the fallback only triggers after timeout and keeps reading order deterministic.

**Does it introduce silent failure risk?**

Low. It only adds another bounded recovery attempt before returning empty text.

---

## 10. Cancellation Test

**If a $1k/month PI firm used this system:**

What would make them cancel?

- A simple scanned packet appears to process but yields no usable events
- OCR fallback looks random or flaky across reruns

**Does this pass eliminate one of those risks?**

Yes. It directly targets the first and partially reduces the second.
