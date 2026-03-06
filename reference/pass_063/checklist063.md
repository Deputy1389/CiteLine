# Pass 063 - OCR Validation

## 1. System State

**Stage**: Hardening -> early Productization

**Signal layer status**: Stable enough on text-based compact packets; OCR path still under-proven

**Leverage layer status**: Not relevant to this pass

**Are we allowed to add features this pass?** No

**If yes, why is this safer than further hardening?**

Not applicable. This is a validation pass.

**Active stage constraints:**

- No weakening OCR thresholds just to make a validation pass green
- No launch claims based on text-based packets alone
- Focus on evidence, not cosmetic pass conditions

---

## 2. Failure Class Targeted

This pass must eliminate or reduce exactly ONE primary failure class:

- [ ] Data integrity failure
- [ ] Narrative inconsistency
- [ ] Required bucket miss
- [ ] Determinism variance
- [ ] Export leakage
- [x] Signal distortion
- [ ] Trust erosion risk
- [ ] Review burden inflation
- [ ] Performance bottleneck
- [ ] Architectural coupling / layer bleed

**Which one is primary?**

Signal distortion

**Optional secondary (only if tightly related):**

Trust erosion risk

**Why is this the highest risk right now?**

The MIMIC validations that passed did not need OCR (`pages_ocr = 0`). That means current launch confidence is based mainly on embedded-text packets. Real law-firm packets frequently include scans and degraded PDFs. OCR health is still a major unproven risk.

---

## 3. Define the Failure Precisely

**What test fails today?**

There is no validated proof that image-only or OCR-degraded packets produce non-empty, citation-backed chronology output without OCR garbage polluting provider/event extraction.

**What artifact proves the issue?**

`reference/pass_056/cloud_batch30_20260305/summary.json` and later summaries show `pages_ocr = 0` across the validated compact batch.

**Is this reproducible across packets?**

Yes. The absence of OCR usage in the validated slice is systemic, not packet-specific.

**Is this systemic or packet-specific?**

Systemic coverage gap.

---

## 4. Define the Binary Success State

After this pass, the following must be true:

**Must be impossible:**

- Claiming OCR readiness without artifact-backed runs on OCR-required packets.

**Must be guaranteed:**

- At least one image-only packet, one degraded packet, and one rasterized packet are run through the current pipeline.
- Each run produces terminal artifacts and explicit OCR metrics.

**Must pass deterministically:**

- OCR-required packets must complete without crash and produce non-empty cited chronology artifacts.

---

## 5. Architectural Move (Not Patch)

This pass makes the following architectural move(s):

- [x] Adding boundary enforcement?
- [ ] Introducing a guard pattern?
- [ ] Consolidating logic?
- [ ] Eliminating duplication?
- [ ] Separating layers more cleanly?

**Describe the move:**

This pass establishes an empirical validation boundary for OCR health. It does not change architecture unless validation reveals a concrete defect.

---

## 6. Invariant Introduced or Strengthened

**Invariant ID**: INV-OV1

**Name**: OCR_PATH_MUST_BE_PROVEN_WITH_OCR_REQUIRED_PACKETS

**What must always be true after this pass?**

OCR readiness claims must be backed by runs on packets that actually trigger OCR fallback.

**Where is it enforced?**

Validation artifact discipline in `reference/pass_063/`.

**Where is it tested?**

Pass-level artifact review and any focused tests added after discovered defects.

**What is added to `governance/invariants.md`?**

Only if this pass exposes and fixes a concrete runtime invariant. Otherwise none.

---

## 7. Tests Added

**Unit tests:**

- none guaranteed up front; depends on discovered OCR defects

**Integration tests (if any):**

- packet-level OCR validation runs and artifact inspection

**Determinism comparison (if applicable):**

- compare rerun status/output shape on OCR-required packet if needed

**Artifact-level assertion (if applicable):**

- `reference/pass_063/summary.json` must include OCR-required packets with non-zero OCR usage where expected

**If no new test is added, justify why:**

This is primarily a validation pass. Code/test additions should only follow a discovered defect.

**Total new tests:** TBD by findings

---

## 8. Risk Reduced

This pass reduces which risks:

- [x] Legal risk
- [x] Trust risk
- [x] Variability
- [ ] Maintenance cost
- [x] Manual review time

**Explain how each checked risk is reduced:**

- Legal risk: cited chronology from scanned packets must be real, not OCR garbage.
- Trust risk: prevents overclaiming readiness.
- Variability: exposes whether OCR path is stable or flaky.
- Manual review time: identifies whether OCR outputs are usable or junk-heavy.

---

## 9. Overfitting Check

**Is this solution generalizable?**

Yes. It validates a whole input class: OCR-required packets.

**Does it depend on a specific test packet?**

No. Minimum set includes three OCR-relevant packet types.

**Could this break other case types?**

Validation itself does not break them.

**Does it introduce silent failure risk?**

No.

---

## 10. Cancellation Test

**If a $1k/month PI firm used this system:**

What would make them cancel?

- Scanned packet produces junk providers / junk chronology
- OCR-required packet appears to process but yields unusable output

**Does this pass eliminate one of those risks?**

Yes. It forces empirical proof or exposes the defect before launch.
