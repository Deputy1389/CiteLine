# Pass34 Plan — 5 Deterministic Leverage Tweaks + LLM Policy

**Status**: PLANNED
**Date**: 2026-03-01
**Scope**: Mediation export rendering only. No pipeline changes, no new extraction,
no new extensions. Pure ordering, suppression, and promotion rules.

---

## Context

Packet reviewed with LLM OFF scored:
- Litigation Readiness: 7.8/10
- Mediation Leverage: 8.2/10
- Credibility / Cleanliness: 8.5/10

Diagnosis conclusion: core engine is strong. Weaknesses are structural ordering issues,
not semantic reasoning issues. 5 deterministic tweaks move this to ~9.2/10 without LLM.

---

## Tweak 1 — Rewrite Page 1 as an Executive Summary (Not a Report)

**Problem**: Page 1 ("CASE SNAPSHOT") reads like an internal QA sheet. Includes pain
score bullets, PT visit count, and record limitations language. Frames the case as
"here's a structured report" instead of "this is a serious injury."

**Fix**: Replace the CASE SNAPSHOT section with a deterministic executive summary
that always outputs exactly this structure, in this order:

```
1. Mechanism + immediate care timing
   "Emergency department evaluation on date of collision."

2. Primary objective pathology
   "Cervical disc displacement with radiculopathy documented."

3. Escalation marker
   "Escalation to imaging and interventional pain management."

4. Duration
   "Documented treatment spanning X months."

5. Specials
   "Medical specials total: $XXX,XXX."
```

**What to remove from page 1:**
- Pain score bullets (8/10 etc.)
- PT visit count
- "Record limitations" / QA notes
- Any treatment intensity summary rows

**Where**: `mediation_sections.py` — the snapshot/executive summary block builder.
If the snapshot is rendered from `timeline_pdf.py`, locate the section that emits
CASE SNAPSHOT and restructure the field selection and ordering there.

**Rules (deterministic, no LLM):**
- Mechanism line: from `extensions.litigation_safe_v1` DOI + first event date delta
- Objective pathology line: select strongest available tier using explicit ranking:
  `radiculopathy > disc_herniation > soft_tissue > no_objective`
  Map the winning tier to a human label (e.g., "radiculopathy" → "Radiculopathy with
  neural involvement documented"). Do NOT rely on arbitrary ordering of findings in
  `selected_tiers.objective` — rank explicitly so edge cases always surface the most
  serious finding.
- Escalation marker: if injection or surgery in events → "interventional pain management"; else if specialist → "specialist management"; else "imaging and ongoing care"
- Duration: (last_event_date - first_event_date) in months, rounded
- Specials: from `extensions.specials_summary.total_billed` if present, else omit

---

## Tweak 2 — Suppress Negative Imaging Noise From Objective Findings

**Problem**: The OBJECTIVE FINDINGS section includes:
- "No acute fracture"
- "No significant degenerative changes"
- "Unremarkable lumbar spine series"
- "No fracture"

These are technically correct but dilute psychological weight. Defense already has them.

**Fix**: Add a suppression filter in the objective findings renderer. Keep only:
- Pathology (disc displacement, herniation, stenosis)
- Neurological involvement (radiculopathy, nerve root compression)
- Intervention triggers (findings that led to injection/surgery)
- Degenerative exclusion IF it directly rebuts a likely defense claim ("no degenerative changes" is worth keeping when defense will argue pre-existing)

**Suppression rule** — exclude any finding where the text contains:
```
"no acute", "no fracture", "unremarkable", "within normal limits",
"no significant", "no evidence of", "negative for"
```
...UNLESS the finding is explicitly flagged as a defense preemption item
(i.e., exists in `extensions.defense_attack_map` as a rebuttal).

**Scope constraint**: Apply this suppression ONLY inside the OBJECTIVE FINDINGS
section of the mediation PDF. Do NOT suppress in:
- Appendices (raw citation index must stay complete)
- Chronology timeline entries
- Any other section

Completeness lives in appendices. Leverage lives in the findings section.

**Where**: `projection_enrichment.py` or `extraction_utils.py` — wherever objective
findings are assembled for the PDF section. Add a filter pass before the findings
are handed to the renderer. Alternatively in `mediation_sections.py` if the objective
findings block is built there.

---

## Tweak 3 — Promote Injection Into Main Escalation Ladder

**Problem**: Injection lives in "Procedures Requiring Date Clarification" — a footnote
section. Visually the case reads as conservative PT-only when it isn't.

**Fix**: If an injection procedure is documented anywhere in the evidence graph (even
without a confirmed date), it must appear in the main TREATMENT PROGRESSION ladder:

```
ED → Imaging → PT → Specialist → Injection
```

**Rule**:
- Check `events` for any event where `event_type == "injection"` OR `procedure_type`
  contains "injection" OR event narrative contains injection keywords
- If found: include in the TREATMENT PROGRESSION section with whatever date is available.
  If date is unresolved, render as: `"Injection performed (see cited record)."` —
  not "Date TBC" (looks clerical) and not omitted (hides leverage).
- Remove from the "Procedures Requiring Date Clarification" bucket once promoted
  (don't show it twice)

**Where**: `timeline_render_utils.py` or `projection_pipeline.py` — where escalation
ladder steps are assembled. Also check `mediation_sections.py` for the treatment
progression block builder.

---

## Tweak 4 — Surface Neurological Deficits as a Dedicated Subsection

**Problem**: Radiculopathy is diagnosed, weakness/reflex/dermatomal findings are in
the citation index (e.g., "C6 4/5 weak" on p.106), but they never appear as a
leverage subsection. These increase jury risk perception significantly.

**Fix**: Add a deterministic "DOCUMENTED NEUROLOGICAL DEFICITS" subsection to the
objective findings or treatment section. If any of these signals exist in evidence
graph events, bullet and cite them:

| Signal | Source |
|---|---|
| Muscle weakness (4/5, 3/5) | exam_findings containing "weak" + grade |
| Diminished/absent reflex | exam_findings containing "reflex" + "diminished"/"absent" |
| Dermatomal numbness | exam_findings containing "numbness"/"paresthesia" + dermatome |
| Positive Spurling sign | exam_findings containing "spurling" |
| Positive straight leg raise | exam_findings containing "straight leg"/"SLR" |
| Positive Phalen/Tinel | exam_findings containing "phalen"/"tinel" |

**Rendering rule**:
- Show subsection only if at least one signal is found
- Each bullet: signal label + verbatim snippet + citation token
- Do not describe or interpret — just list
- Cap at 3–4 bullets maximum — too many exam snippets reduces impact; rank by
  clinical severity (weakness > reflex loss > dermatomal > provocation sign)
- Omit subsection entirely if no signals (no placeholder)

**Where**: New helper in `mediation_sections.py` → `_build_neuro_deficit_subsection()`.
Reads from `projection_entries` event `exam_findings` fields and/or from
`extensions.claim_rows` entries tagged with neurological content.

---

## Tweak 5 — Resolve Gap Messaging Inconsistency

**Problem**: Timeline summary page shows "Treatment gap detected (171 days)" but
Appendix C shows "No treatment gaps detected." Contradiction noticed immediately
by defense counsel.

**Fix**: Single source of truth for gap status. Both the summary and Appendix C
must read from the same computed gap list.

**Rule**:
- Gap list is `extensions.missing_records.gaps` (already computed, already in evidence graph)
- Summary page: if `len(gaps) > 0` → show gap(s) with duration; else omit gap mention
- Appendix C: if `len(gaps) > 0` → list gap(s); else "No treatment gaps identified"
- Both read from the same list — no separate detection logic

**Where**:
- Summary/snapshot page: `mediation_sections.py` or `timeline_pdf.py` summary block
- Appendix C: `appendices_pdf.py` — gap section
- Both must call the same helper or read from the same `gaps` field

**Root cause to check**: Is Appendix C running its own gap detection instead of
reading from `extensions.missing_records.gaps`? If so, **delete that logic entirely**
and route both to the shared source. Do not refactor it — remove it.
Duplication is the enemy. There must be exactly one place gap truth is computed,
and it is the pipeline, not the renderer.

---

## Part 2 — LLM Policy

### Mediation Export: LLM permanently disabled

Enforce at **pipeline entry**, not inside the renderer. The guard must fire before
any LLM pre-processing, any optional enrichment layer, and any narrative builder:

```python
# In pipeline.py, immediately after export_mode is resolved — before any step runs:
if export_mode == "MEDIATION":
    config.enable_llm_reasoning = False
```

Never block a mediation export because LLM is unavailable. If any code path
checks for LLM availability and would fail — fail gracefully to deterministic output.
The mediation export must complete regardless of LLM quota or availability.

**Why pipeline entry, not renderer**: Guarding inside the renderer is too late.
LLM could have already run in an earlier enrichment step, contaminating the data
before it ever reaches the renderer.

**Marketing copy unlocked**: "No generative AI is used in mediation exports.
Every statement is deterministically derived from cited medical records."

### Internal Mode: LLM optional for drafting

LLM is allowed (if available) only for:
- Demand letter polish in `internal_demand_package`
- Associate drafting suggestions
- Executive summary rewrite suggestions (INTERNAL tab only)

LLM must NOT be used for:
- Evidence graph generation
- Chronology ordering
- Objective tier detection
- Escalation ladder
- Risk flag detection
- Gap detection
- Billing totals
- Demand multiplier math

### Fail-safe rule

If LLM call fails or quota exceeded:
- Log the failure
- Continue with deterministic output
- Never raise or block the export
- Surface in `export_artifacts_metadata` as `"llm_polish_applied": false`

This applies to both MEDIATION and INTERNAL modes. Persist whether LLM was applied
so debugging is unambiguous — "did the LLM run or not?" must always be answerable.

### Config surface

Add to `RunConfig` (if not already present):
```python
enable_llm_for_mediation: bool = False   # permanently off for mediation
llm_polish_internal: bool = True          # optional in internal mode
```

---

## Files Changed

| File | Change |
|---|---|
| `apps/worker/steps/export_render/mediation_sections.py` | Tweak 1 (page 1 exec summary), Tweak 4 (neuro deficit subsection), Tweak 5 (gap source of truth) |
| `apps/worker/steps/export_render/projection_enrichment.py` or `extraction_utils.py` | Tweak 2 (negative imaging suppression) |
| `apps/worker/steps/export_render/timeline_render_utils.py` or `projection_pipeline.py` | Tweak 3 (injection promotion into escalation ladder) |
| `apps/worker/steps/export_render/appendices_pdf.py` | Tweak 5 (Appendix C reads from shared gap source) |
| `apps/worker/pipeline.py` | LLM policy — disable for MEDIATION, graceful fallback |
| `packages/shared/models/domain.py` | Add `enable_llm_for_mediation: bool = False` to RunConfig if needed |

---

## What Does NOT Change

- Evidence graph generation — untouched
- Chronology logic — untouched
- CSI / settlement model / internal demand — untouched
- All quality gate scores — must remain green (zero regression deltas)
- MEDIATION strip logic — untouched

---

## Gold Run Acceptance Criteria

Both packets (05_minor_quick, batch_029_complex_prior) must:
- Pass all quality gates with zero regression deltas vs Pass33
- Page 1 of MEDIATION PDF contains: mechanism, objective pathology, escalation, duration, specials — no pain scores, no PT count, no QA notes
- Objective findings section contains no "no fracture" / "unremarkable" noise lines (unless defense preemption flagged)
- Injection present in main escalation ladder if documented in events
- Gap status consistent between summary and Appendix C
- No LLM calls made during MEDIATION export (verify via log or `llm_polish_applied: false` in artifacts metadata)
