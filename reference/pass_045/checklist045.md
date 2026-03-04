# Pass 045 Checklist — Row Key Finding Repair + Unverified Quarantine + Packet Integrity

## A) Row Key Finding Fix (INV-Q4)

- [ ] Add `_best_key_finding(fact_pairs, event_page)` function to `timeline_pdf.py`
  - Score each candidate fact by `abs(fact.page_number - event_page)`
  - Pick lowest distance; ties broken by original order (first wins)
  - If no page info available, fall back to original `candidate_pairs[0]` behaviour
- [ ] Replace line ~2497 `key_finding_raw, key_is_verbatim = candidate_pairs[0]` with `_best_key_finding()`
- [ ] Unit test: event at page 12, facts on pages [3, 11, 14] → page 11 fact wins (distance=1 vs 9 vs 2 → tie-break page 11 vs page 14 → page 11)
- [ ] Verify no regression on existing 6 cases

## B) Unverified Content Quarantine (INV-Q5)

- [ ] Inspect `step_renderer_manifest.py` for whether `alignment_status != PASS` items set `headline_eligible=True` or drive tier signals
- [ ] If they can: add a guard that sets `headline_eligible=False` for any item where `alignment_status not in {None, "", "PASS"}`
- [ ] Confirm `Additional Findings (Context Not Fully Verified)` section is gated to INTERNAL only (already in code at line 2418) — add a regression assertion to confirm this
- [ ] Add `INV-Q5` to `governance/invariants.md`

## C) Cross-Contamination Regression Fixture (INV-Q6)

- [ ] Create `tests/fixtures/invariants/case7_cross_contamination/`
- [ ] Create minimal `evidence_graph.json` with:
  - Primary injury: shoulder fracture events (imaging, ED, ortho)
  - Unrelated section: renal calculus / CT kidney events (different patient partition / different segment)
- [ ] Create `fixture_manifest.json` with expectations:
  - `cross_contamination_quarantined: true` (kidney findings not in snapshot)
  - That kidney-origin events don't set `has_radiculopathy`, `has_surgery_dated`, etc.
- [ ] Add a harness check: events from segments classified as `unrelated` must not appear in `leverage_index_result.driving_signals`
- [ ] Verify `case7_cross_contamination` FIXTURE_MANIFEST PASS on regression

## D) Real Packet for Cloud Runs

- [ ] Identify a realistic packet in `PacketIntake/` that is NOT `batch_029_complex_prior`
  - Check `PacketIntake/` for packets that produce non-`needs_review` status
  - Or use a fixture-derived packet with real-looking provider names
- [ ] Run the cloud pass with that packet
- [ ] Download `export_INTERNAL.pdf` and `export_MEDIATION.pdf` to `reference/pass_045/`

## E) Governance

- [ ] Append INV-Q4, INV-Q5, INV-Q6 to `governance/invariants.md`
- [ ] Write `reference/pass_045/release_notes.md`

## F) Regression + Deploy

- [ ] Run full local regression (7 cases) → CASES PASS, DRIFT PASS
- [ ] Commit + push to GitHub
- [ ] Deploy to Oracle worker
- [ ] Run cloud packet, download outputs

---

## Acceptance Gates

| Gate | Status |
|------|--------|
| `_best_key_finding` unit test passes | [ ] |
| `case7_cross_contamination` FIXTURE_MANIFEST PASS | [ ] |
| Full regression 7/7 CASES PASS, DRIFT PASS | [ ] |
| Cloud INTERNAL + MEDIATION PDFs in pass_045 | [ ] |
| Release notes written | [ ] |
