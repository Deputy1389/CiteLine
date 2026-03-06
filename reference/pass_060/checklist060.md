PASS TITLE: Pass 060 - Promoted Finding Hygiene Floor

1. System State

We are in: Hardening -> early Productization.

Are we allowed to add features this pass? No.

Why: the current issue is not missing capability. It is trust erosion caused by weak claim promotion. The safe move is boundary enforcement on existing manifest selection, not broader feature work.

2. Failure Class Targeted

Primary failure class: Trust erosion risk.

Secondary risk: Review burden inflation.

Why this is highest risk now:
- Passes 056-059 made the pipeline survive and complete successfully on compact MIMIC packets.
- The remaining visible defect is attorney-facing output hygiene: Page 1 can be populated with generic or administrative promoted findings that are citation-backed but not litigation-useful.
- This directly violates the attorney value hierarchy in `AGENTS.md` because the renderer ends up elevating weak synthetic/admin content instead of the strongest objective findings.

3. Define the Failure Precisely

What test fails today:
- `RendererManifest.promoted_findings` accepts low-signal claim rows such as synthetic diagnosis labels (`Medical Condition B20`), admission record numbers, admission/discharge timestamp boilerplate, and generic treatment/admin lines.
- Those items can appear as headline-eligible promoted findings despite weak support and low attorney value.

What artifact proves the issue:
- `reference/pass_059/cloud_rerun_patient_10002930/evidence_graph.json`
- In that artifact, `extensions.renderer_manifest.promoted_findings` includes generic labels like `PRIMARY DIAGNOSIS: Medical Condition B20` and `ADMISSION RECORD: #22380825`.

Is this reproducible across packets:
- Yes for synthetic MIMIC-style packets with generic diagnosis/treatment wording.

Is this systemic or packet-specific:
- Systemic. The promotion path in `step_renderer_manifest.py` is permissive for all claim rows with citations and does not enforce a semantic quality floor.

4. Define the Binary Success State

After this pass:
- It must be impossible for generic synthetic diagnosis labels, administrative record identifiers, pure admit/discharge timestamp lines, or low-signal treatment boilerplate to appear in `renderer_manifest.promoted_findings`.
- Citation-backed substantive findings must still be promotable.
- Promotion output must remain deterministic for the same claim rows.

Binary success criteria:
- Generic/admin claim rows are absent from `RendererManifest.promoted_findings`.
- Substantive diagnosis/imaging/objective/procedure rows with citations remain present.
- Rebuilding the manifest from the same input yields the same promoted findings set and order.

5. Architectural Move (Not Patch)

This pass introduces boundary enforcement at the manifest contract.

Architectural move:
- Add a semantic hygiene guard to the claim-row -> promoted-finding selection boundary.
- Keep renderer display-only.
- Consolidate quality gating for promoted findings in the pipeline manifest builder instead of allowing downstream rendering to inherit noisy claim rows.

6. Invariant Introduced

Invariant:
- `INV-PF1`: A promoted finding must be citation-backed and semantically substantive; synthetic/admin boilerplate may not be promoted.

Where enforced:
- `apps/worker/steps/step_renderer_manifest.py`

Where tested:
- New unit tests in `tests/unit/test_renderer_manifest.py`

7. Tests Added

Exact tests:
- Unit: generic synthetic diagnosis labels are suppressed from promoted findings.
- Unit: administrative/timestamp treatment lines are suppressed from promoted findings.
- Unit: substantive citation-backed findings still survive promotion.
- Artifact-level assertion: known MIMIC artifact rebuild yields a materially reduced promoted finding set without losing substantive categories.

8. Risk Reduced

This pass reduces:
- Trust risk
- Legal risk
- Manual review time
- Maintenance cost

How:
- Attorneys stop seeing low-value or misleading headline findings.
- Page 1 better matches the product's litigation-safe value hierarchy.
- Reviewers spend less time filtering obvious junk that should never have been elevated.

9. Overfitting Check

Is this solution generalizable:
- Yes. It targets semantic classes of low-value claim text, not one packet ID.

Does it depend on batch029:
- No.

Could this break other buckets:
- It could suppress legitimate claims if the filters are too broad, so tests must prove substantive diagnosis/imaging/objective/procedure claims still promote.

Does it introduce silent failure risk:
- Low if the hygiene guard is deterministic and covered by tests.

Cancellation Test

If a $1k/month PI firm used this system:
- They would cancel if Page 1 elevated generic synthetic diagnoses, record numbers, or boilerplate instead of meaningful medical findings.
- This pass directly eliminates one of those risks by preventing weak claim promotion at the manifest boundary.
