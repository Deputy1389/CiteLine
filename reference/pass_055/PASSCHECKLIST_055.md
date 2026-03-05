PASS TITLE: Pass 055 — Workspace Actions & Export Layer

---

1️⃣ System State

Stage: Productization — workspace UI is live (Pass 054), backend registries complete (Pass 053), pipeline stable.

Are we allowed to add features this pass? Yes.

Why is that safer than further hardening?
The core extraction pipeline is stable and tested across multiple case types. The immediate risk to retention is not data quality — it is that attorneys can READ the intelligence but cannot ACT on it. A workspace that displays findings without enabling exports or narrative generation is not a workflow tool; it is a reference panel. Attorneys who cannot generate a demand letter or export a mediation packet within the product will revert to their existing tools, making Citeline additive work rather than workflow replacement.

---

2️⃣ Failure Class Targeted

Primary: ☒ Review burden inflation

The attorney opens the workspace, sees correct findings, then exits and manually writes the demand letter in Word — from scratch. The AI work ends at display. This is the same workflow burden the attorney had before Citeline, minus the extraction step.

Secondary: ☒ Trust erosion risk

An attorney cannot validate AI output by editing it. Without an editable demand builder, the attorney has no mechanism to correct, annotate, or take ownership of the narrative. Uneditable AI output is not used in legal practice.

Why this is the highest risk right now:
- Pass 054 shipped a complete read-only workspace. Without actionable exports in Pass 055, attorney beta feedback will be "impressive but I can't use it in my actual workflow." That feedback is fatal to sales.
- The demand letter is the single highest-time-cost document in PI practice (2–4 hours per case). Eliminating it is the product's core value proposition. It must ship.

---

3️⃣ Define the Failure Precisely

What fails today:
- Clicking "Build demand narrative" in PrepPackTab shows a toast: "Coming in next release."
- Clicking "Mediation Packet" shows a locked card.
- PDF viewer shows pages with no indication of which claims cite that page.
- Tab 6 is entirely stub content.

What artifact proves the issue:
- Live workspace at `/app/cases/[caseId]/review?tab=prep` — both action cards are stubs.
- `components/workspace/PrepPackTab.tsx` — stubs confirmed in code.

Is this reproducible across packets? Yes — the stubs are unconditional.

Is this systemic or packet-specific? Systemic — no case ever reaches an actionable export.

---

4️⃣ Define the Binary Success State

After this pass:

What must be impossible:
- An attorney opening the workspace cannot be left without a mechanism to export a demand narrative.
- The demand builder cannot generate uncited claims (every section must contain at least one citation reference from the evidence graph).
- The mediation packet export cannot render workspace chrome in the printed PDF.

What must be guaranteed:
- Clicking "Generate Demand" produces structured sections with citations in < 20 seconds.
- Clicking `↺` on a single section regenerates only that section; all other sections are untouched.
- Every generated section is editable before download.
- All text edits are persisted to the `draft_demands` table — a page refresh loads the same draft.
- "Download PDF" produces a clean, printable demand narrative in the browser.
- Mediation packet renders from existing evidence graph data without any new pipeline run.
- Evidence anchor overlay shows correct citation count badge on any PDF page that has citations.

What must pass deterministically:
- "Given the same evidence graph, the demand builder prompt contains the same structured input context." (Prompt construction is deterministic even if LLM output varies.)
- "Mediation packet renders with zero placeholder text (Unknown provider, 1900-01-01, Not available) for any case where the evidence graph is complete."

---

5️⃣ Architectural Move (Not Patch)

This pass is: **Separating layers more cleanly.**

The demand builder introduces a hard boundary:
- **Pipeline layer**: extracts facts, builds registries, assigns citations. Already done.
- **Narrative layer (new)**: consumes pipeline output via a typed interface, generates attorney-facing prose. The LLM is a formatter for structured data, not an extractor.

This is the correct architectural position for LLM in the system. The LLM never sees raw PDFs or makes clinical judgments — it receives structured, citation-keyed facts from the pipeline and generates prose. This keeps the pipeline as the single source of truth and the LLM as a downstream consumer.

This is NOT a patch — it is the completion of the pipeline → narrative → export flow that was always the intended architecture.

---

6️⃣ Invariant Introduced

**Invariant: Every demand narrative section returned by the API contains at least one citation_id that exists in the evidence graph.**

Enforced: In the backend endpoint (`demand.py`) — after LLM response is parsed, validate that each section's `citations` array is non-empty and that all cited IDs are present in the run's evidence graph. Reject and retry (up to 2 times) if not.

Tested:
- Unit test: `test_demand_narrative_citations.py` — mock LLM response with missing citations → endpoint returns 422.
- Integration test: real evidence graph → demand narrative → all section citation_ids resolve to known CitationRefs.

**Invariant: Mediation packet never renders placeholder text.**

Enforced: Adapter function `buildMediationPacketSections()` — raises if any required field (provider name, date, diagnosis) is null/empty/"Unknown"/"Not available" when its source registry entry is non-empty.

Tested: `test_mediation_packet_no_placeholders.py` — fixture with partial evidence graph → assert placeholder strings are absent from rendered output.

---

7️⃣ Tests Added

Unit tests (C:\Citeline\tests\unit\):
- `test_demand_narrative_citations.py` — citation validation invariant (mock LLM)
- `test_demand_prompt_construction.py` — given a fixture evidence graph, prompt structure is deterministic and contains required keys (injury_clusters, causation_timeline, settlement_posture)
- `test_demand_section_regenerate.py` — POST with `section="injuries"` updates only the injuries key in the stored draft; other sections unchanged
- `test_draft_demands_persistence.py` — create draft → PATCH section text → GET draft → text matches
- `test_mediation_packet_no_placeholders.py` — no placeholder strings in rendered mediation sections

Integration tests:
- `test_demand_narrative_endpoint.py` — POST /matters/{id}/demand-narrative with real evidence graph → valid structured response with citations + draft_id in response
- `test_demand_draft_round_trip.py` — generate → edit section via PATCH → reload via GET → edited text persists
- `test_mediation_packet_render.py` — evidence graph with mediation_sections → all 5 packet sections render with real content

No determinism comparison required: LLM output varies by design. Invariant is on input structure (prompt determinism) and output structure (citations present), not on text content.

If no test is added for the frontend editable sections: justified — component behaviour (text editing, download trigger) is covered by manual QA against a real case. Unit-testing a textarea is low value.

---

8️⃣ Risk Reduced

☒ Trust risk — Attorney can edit, review, and take ownership of AI-generated narrative before it leaves the product. Uneditable output is not usable in legal practice.

☒ Manual review time — Demand letter generation (2–4 hours per case) is replaced by a < 20 second generation + 15 minute review and edit cycle.

☒ Legal risk — Every narrative claim is citation-anchored to a source page. The attorney sees exactly what the AI is basing each statement on. No speculation reaches the final document without attorney review.

How:
- The demand builder does not auto-submit. It generates a draft that the attorney must review, edit if needed, then explicitly download. Attorney remains the author of record.
- All cited page references are visible inline, allowing the attorney to verify before download.

---

9️⃣ Overfitting Check

Is this solution generalizable?
- The demand builder prompt receives typed structured data (injury_clusters, causation_timeline, billing_summary) — not raw text or packet-specific keywords. Generalizes across all case types.
- The mediation packet adapter reads from `extensions.*` keys that are populated for all completed runs.
- The evidence anchor overlay uses `citation.page_number` which is present on every CitationRef regardless of case type.

Does it depend on batch029? No. All three features work from any completed evidence graph.

Could this break other buckets? No. This pass adds new endpoints and UI — no changes to the pipeline, extraction, or renderer.

Does it introduce silent failure risk?
- Demand builder: LLM failure returns HTTP 500 with a user-visible error. No silent failure.
- Mediation packet: if `mediation_sections` is absent from extensions, show a clear "Mediation analysis not available for this run" message. Not silent.
- Evidence anchor: if `pageIndex` is empty, badges simply don't appear. Graceful degradation.

---

🔟 Cancellation Test

If a $1k/month PI firm used this system, what would make them cancel?

Primary: "We still have to write the demand letter ourselves. We're paying for a better file organizer, not a time-saver."

Does this pass eliminate that risk? **Yes.** The demand builder directly addresses this. If a firm can generate a draft demand in < 20 seconds and edit it to completion, the ROI is immediate and tangible.

Secondary: "We can't show the AI's work. If opposing counsel challenges a claim, we can't trace it."

Does this pass address that? **Yes.** The citation chips in every generated section + the PDF viewer evidence anchor overlay make every claim traceable to a source page. The attorney can answer "where did this come from?" for any statement in the demand letter.

---

Additional Constraints for Pass 055

- LLM (Claude Sonnet) is a narrative formatter only — it receives structured, citation-keyed facts. It does not receive raw PDF text or make clinical determinations.
- Per-section regeneration must not touch sibling sections — merge is server-side into the draft row, not a full re-generation.
- Draft auto-save is debounced (500ms) — not on every keystroke, not on download only.
- Demand builder does not auto-send. Attorney must explicitly click Download.
- Tone selector (aggressive / moderate / conservative) changes the system prompt only — it does not change what facts are presented, only how they are framed.
- Mediation packet render uses existing pipeline data only — no new pipeline step, no new worker run required.
- Every citation chip rendered in the demand builder must resolve to a real `CitationRef` in the loaded evidence graph.
- Evidence anchor overlay must degrade gracefully (no badge = no citations on that page, not an error).
- No medical keywords in any UI component (inherited rule from CLAUDE.md).
- Renderer is display-only — demand builder generates via API, not client-side.

Do not begin implementation until this checklist is reviewed.
