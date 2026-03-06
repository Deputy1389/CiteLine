# Pass 062 - Sparse Packet Case Skeleton

## 1. System State

**Stage**: Hardening -> early Productization

**Signal layer status**: Locked enough for pilot-oriented hardening; chronology hardening advanced through passes 56-61

**Leverage layer status**: Implemented but not the focus of this pass

**Are we allowed to add features this pass?** Yes

**If yes, why is this safer than further hardening?**

This feature is a deterministic fallback over already-extracted structure. It reduces trust erosion without adding inference, narrative generation, or new extraction risk. It improves lawyer orientation while preserving the conservative behavior introduced in passes 60-61.

**Active stage constraints:**

- No generative fallback for sparse packets
- Renderer remains display-only
- No weakening of citation requirements for substantive findings
- No chronology extraction changes in this pass

---

## 2. Failure Class Targeted

This pass must eliminate or reduce exactly ONE primary failure class:

- [ ] Data integrity failure
- [ ] Narrative inconsistency
- [ ] Required bucket miss
- [ ] Determinism variance
- [ ] Export leakage
- [ ] Signal distortion
- [x] Trust erosion risk
- [ ] Review burden inflation
- [ ] Performance bottleneck
- [ ] Architectural coupling / layer bleed

**Which one is primary?**

Trust erosion risk

**Optional secondary (only if tightly related):**

Review burden inflation

**Why is this the highest risk right now?**

Passes 60-61 correctly made sparse packets prefer emptiness over junk. That removed embarrassing output, but the result still feels low-value to lawyers because Page 1 provides too little orientation when no promotable anchors exist.

---

## 3. Define the Failure Precisely

**What test fails today?**

A sparse but valid packet can produce a clean Page 1 with no promotable anchors and no structured orientation block, making the output feel like the system did nothing.

**What artifact proves the issue?**

`reference/run_113f2e1a790642489df8ca003f9ce70d_pdf.pdf`

**Is this reproducible across packets?**

Yes, across sparse packets where `top_case_drivers == []` and `promoted_findings == []`.

**Is this systemic or packet-specific?**

Systemic. There is no typed manifest fallback for sparse packets.

---

## 4. Define the Binary Success State

After this pass, the following must be true:

**Must be impossible:**

- Sparse packets with no top anchors must not render a Page-1 orientation vacuum.

**Must be guaranteed:**

- When `top_case_drivers == []`, a deterministic `Case Skeleton` block is available from the manifest if enough structured facts exist.
- The skeleton must use already-extracted facts only.

**Must pass deterministically:**

- Rebuilding the manifest from the same events/citations produces the same case skeleton items and order.
- Rendering the same sparse manifest produces the same Page-1 skeleton block.

---

## 5. Architectural Move (Not Patch)

This pass makes the following architectural move(s):

- [x] Adding boundary enforcement?
- [ ] Introducing a guard pattern?
- [x] Consolidating logic?
- [ ] Eliminating duplication?
- [x] Separating layers more cleanly?

**Describe the move:**

Add a typed sparse-packet fallback structure to `RendererManifest` and render it only when top anchors are absent. The pipeline decides the structured snapshot; the renderer displays it.

---

## 6. Invariant Introduced or Strengthened

**Invariant ID**: INV-CS1

**Name**: CASE_SKELETON_ONLY_WHEN_SPARSE

**What must always be true after this pass?**

If `renderer_manifest.top_case_drivers` is empty and structured sparse-packet facts exist, `renderer_manifest.case_skeleton.active` must be true and citation-backed orientation items must be available.

**Where is it enforced?**

`apps/worker/steps/step_renderer_manifest.py`

**Where is it tested?**

`tests/unit/test_renderer_manifest.py` and `tests/unit/test_pdf_quality_gate.py`

**What is added to `governance/invariants.md`?**

A pass-62 registry entry for `INV-CS1`.

---

## 7. Tests Added

**Unit tests:**

- `tests/unit/test_renderer_manifest.py :: test_renderer_manifest_builds_case_skeleton_for_sparse_packet` - asserts skeleton is built for sparse packet
- `tests/unit/test_renderer_manifest.py :: test_renderer_manifest_omits_case_skeleton_when_substantive_top_drivers_exist` - asserts no fallback for substantive packet
- `tests/unit/test_pdf_quality_gate.py :: test_pdf_renders_case_skeleton_for_sparse_packet_when_top_anchors_absent` - asserts Page 1 renders the skeleton

**Integration tests (if any):**

- none in this pass

**Determinism comparison (if applicable):**

- manifest builder order and content are deterministic by construction and covered in unit assertions

**Artifact-level assertion (if applicable):**

- pass-62 validation artifacts should show case skeleton on sparse packet rerun

**If no new test is added, justify why:**

Not applicable

**Total new tests:** 3

---

## 8. Risk Reduced

This pass reduces which risks:

- [x] Legal risk
- [x] Trust risk
- [x] Variability
- [ ] Maintenance cost
- [x] Manual review time

**Explain how each checked risk is reduced:**

- Legal risk: the fallback stays deterministic and citation-backed instead of inventing narrative.
- Trust risk: lawyers get orientation instead of an apparently empty front page.
- Variability: the fallback is typed in manifest rather than improvised in the renderer.
- Manual review time: operators can orient themselves faster on thin packets.

---

## 9. Overfitting Check

**Is this solution generalizable?**

Yes. It targets sparse packets as a class.

**Does it depend on a specific test packet?**

No.

**Could this break other case types?**

Low risk if it only activates when top anchors are absent.

**Does it introduce silent failure risk?**

Low. The fallback is explicit and typed.

---

## 10. Cancellation Test

**If a $1k/month PI firm used this system:**

What would make them cancel?

- A front page that looks like the system found nothing
- Sparse packets that feel unusable despite valid chronology work

**Does this pass eliminate one of those risks?**

Yes. It converts sparse-packet emptiness into structured orientation without adding junk.

---

## Prohibited Behaviors Check (govpreplan §10)

Confirm none of the following are introduced by this pass:

- [x] Silent fallback logic
- [x] Renderer inference (renderer computes anything)
- [x] Non-deterministic ordering
- [x] Hidden policy defaults
- [x] Direct EvidenceGraph access from Trajectory
- [x] Fixing tests by hiding outputs instead of correcting logic
- [x] Policy changes without version increment

---

## Invariant Registry Update

- [x] `governance/invariants.md` will be updated with all new invariants introduced by this pass
- [x] No existing invariant is silently removed or weakened

---

## Checklist Summary

| Section | Status | Note |
|---|---|---|
| 1 System State | complete | Sparse packet fallback only |
| 2 Failure Class | complete | Trust erosion |
| 3 Failure Defined | complete | Sparse Page-1 orientation gap |
| 4 Binary Success | complete | Typed deterministic skeleton |
| 5 Arch Move | complete | Manifest contract extension |
| 6 Invariants | complete | INV-CS1 |
| 7 Tests | complete | 3 tests planned |
| 8 Risk Reduced | complete | Trust + review burden |
| 9 Overfitting | complete | General sparse-packet rule |
| 10 Cancellation | complete | Prevents empty-feeling output |
| Prohibited Behaviors | complete | none introduced |
| Registry Update | complete | pending code change |
