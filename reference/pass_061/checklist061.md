PASS TITLE: Pass 061 - Top Case Driver Hygiene

1. System State

We are in: Hardening -> early Productization.

Are we allowed to add features this pass? No.

Why: the issue is attorney-facing anchor pollution, not missing functionality. The safe move is stricter driver selection at the manifest boundary.

2. Failure Class Targeted

Primary failure class: Trust erosion risk.

Secondary risk: Review burden inflation.

Why this is highest risk right now:
- Pass 060 removed low-value `promoted_findings`.
- Cloud validation still showed Page 1 pollution in `Top Record Anchors` because `renderer_manifest.top_case_drivers` still pointed at synthetic/admin events.
- That means the product still surfaces junk at the exact place attorneys look first.

3. Define the Failure Precisely

What fails today:
- `top_case_drivers` accepts event IDs whose supporting claim rows are synthetic diagnoses, admin record identifiers, timing boilerplate, or lab-panel-only lines.
- The PDF then renders those events as top anchors.

What artifact proves the issue:
- `reference/run_e9f43b7cb1d44961b65bf6b50a3bb262_evidence_graph.json`
- `reference/run_e9f43b7cb1d44961b65bf6b50a3bb262_pdf.pdf`

Is this reproducible across packets:
- Yes for compact synthetic packets with generic claim rows.

Is this systemic or packet-specific:
- Systemic. `_top_case_drivers_from_claim_rows()` and `_top_case_driver_fallback_from_events()` are permissive.

4. Define the Binary Success State

After this pass:
- It must be impossible for `top_case_drivers` to contain event IDs backed only by synthetic/admin/timing/lab-only content.
- If a packet has no substantive top anchors, the manifest must prefer an empty `top_case_drivers` list over junk.
- Top-anchor selection must remain deterministic.

5. Architectural Move (Not Patch)

Architectural move:
- Add a semantic hygiene floor to manifest driver selection.
- Reuse the same low-value classes established in pass 060.
- Keep renderer display-only.

6. Invariant Introduced

Invariant:
- `INV-TD1`: `top_case_drivers` may reference only citation-backed events with at least one substantive driver assertion.

Where enforced:
- `apps/worker/steps/step_renderer_manifest.py`

Where tested:
- `tests/unit/test_renderer_manifest.py`

7. Tests Added

Exact tests:
- Unit: low-value synthetic/admin rows yield no `top_case_drivers`.
- Unit: substantive diagnosis/procedure rows still produce `top_case_drivers`.
- Unit: low-value event fallback does not repopulate `top_case_drivers`.

8. Risk Reduced

This pass reduces:
- Trust risk
- Legal risk
- Manual review time

How:
- Page 1 top anchors stop advertising junk as case-driving medical facts.

9. Overfitting Check

Is this solution generalizable:
- Yes. It filters semantic low-value classes, not one packet ID.

Does it depend on batch029:
- No.

Could this break other buckets:
- It could over-suppress if too broad, so substantive-anchor preservation tests are required.

Does it introduce silent failure risk:
- Low. Empty `top_case_drivers` is preferable to junk and is easy to validate.

Cancellation Test

If a PI firm used this system:
- They would cancel if the front page still called record numbers and synthetic diagnosis placeholders “Top Case-Driving Events.”
- This pass removes that risk at the manifest driver-selection layer.
