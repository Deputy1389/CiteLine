# Pass34: Deterministic Mediation Leverage Tweaks — Findings

**Date**: 2026-03-01
**Commit**: d5f6abd
**Export mode**: MEDIATION (LLM OFF — enforced)
**Packets tested**: 05_minor_quick, batch_029_complex_prior
**Deterministic parity**: ✅ True on both packets (A/B runs identical)

---

## Changes Made

### Tweak 1 — Deterministic Executive Summary (Page 1)

**File**: `apps/worker/steps/export_render/timeline_pdf.py`, `mediation_sections.py`

**Problem**: Page 1 in MEDIATION mode previously showed a generic case highlights block ("Emergency department treatment…highlights below…") that was template noise, not derived from citation-anchored data.

**Fix**: Added `build_mediation_exec_summary_items()` to `mediation_sections.py`. When `export_mode == MEDIATION`, renders a 5-line deterministic block directly under the header table:
- Line 1: Mechanism (from DOI / mechanism extension)
- Line 2: Highest-tier objective pathology (severity_profile tier rank)
- Line 3: Treatment escalation stages documented (ED → imaging → specialist → procedure/surgery)
- Line 4: Care duration
- Line 5: Specials status (extracted total or "not captured")

The old generic highlight block is suppressed entirely in MEDIATION mode. Record-limitations warnings are also suppressed — they are internal quality flags, not leverage.

**Observed output** (batch029):
```
- Emergency department evaluation on 2024-10-11.
- Radiculopathy with neural involvement documented. [p. 112] [p. 113] [p. 114]
- Escalation to imaging and ongoing care documented.
- Documented treatment spanning 13 months.
```

---

### Tweak 2 — Negative Imaging Noise Filter (Mediation Objective Findings)

**File**: `apps/worker/steps/export_render/mediation_sections.py`

**Problem**: The OBJECTIVE FINDINGS section of the mediation leverage brief (Page 3) included negative imaging phrases like "Unremarkable lumbar spine series" and "No acute fracture" that are defense-friendly ammunition, not leverage.

**Fix**: Added `_NEGATIVE_IMAGING_NOISE` regex and `_is_defense_preemption_finding()` helper. In `_build_objective_findings_section()`, any label matching the noise pattern is skipped unless:
- The defense_attack_map has `PRIOR_SIMILAR_INJURY` triggered AND the label mentions "degenerative"

**Noise pattern** (suppressed):
```
no acute | no fracture | unremarkable | within normal limits | no significant | no evidence of | negative for
```

**Observed output** (batch029): The "Unremarkable lumbar spine series" which appeared in the timeline table was correctly kept in the chronological record (timeline page) but suppressed from the OBJECTIVE FINDINGS mediation section. The positive finding "Mild straightening of lordosis suggestive of spasm" remained.

**Note**: This filter only applies to the mediation `_build_objective_findings_section()`. The medical timeline table and appendices are unaffected — the original record text is always preserved.

---

### Tweak 3 — Injection Promotion Without Confirmed Date

**File**: `apps/worker/steps/export_render/mediation_sections.py`

**Problem**: Injections without a confirmed calendar date were silently omitted from the TREATMENT PROGRESSION escalation ladder, hiding a significant treatment escalation event.

**Fix**: `_detect_stages()` now checks `rm.get("promoted_findings")` for injection-type items (category `procedure` or `injection`, or label containing injection keywords). If found, the `procedure` stage is added to the present stages. In the escalation ladder, undated procedure stages render as `"Injection performed (see cited record)."` instead of the normal date-anchored label.

**Observed output**: Neither test packet had documented injections, so this tweak was not triggered. Would activate on cases where the renderer manifest flags an injection but the extraction date is uncertain.

---

### Tweak 4 — Documented Neurological Deficits Subsection

**File**: `apps/worker/steps/export_render/mediation_sections.py`

**Problem**: Neurological examination findings (reflex loss, dermatomal deficits, positive Spurling/SLR) were buried in the full timeline and not surfaced as a distinct leverage section.

**Fix**: Added `_build_neuro_deficit_subsection()` (key: `neuro_deficits`, `gate_required=False`). Scans `exam_findings`, `diagnoses`, and `facts` from raw events plus `claim_rows` from extensions. Detects six signal categories ranked by severity:

| Rank | Signal | Pattern |
|------|--------|---------|
| 0 | Muscle weakness | 4/5, 3/5, weakness |
| 1 | Diminished/absent reflex | reflex + diminished/absent |
| 2 | Dermatomal deficit | numbness/paresthesia + C/L/S level |
| 3 | Positive Spurling sign | "spurling" |
| 4 | Positive straight leg raise | "positive SLR/straight leg" |
| 5 | Phalen/Tinel sign | "phalen", "tinel" |

Caps at 4 bullets, ranked most severe first. Section is omitted entirely (no placeholder) if no signals detected.

**Observed output**: Both test packets returned no structured neurological exam findings in `exam_findings` (all events had `exam_findings: []`). The batch029 case has "Radiculopathy" diagnosed and nerve-root text in facts, but these don't match the specific exam signal patterns. The section is correctly omitted for both packets.

**Note**: This section will activate on packets with structured neuro exam data — e.g., orthopedic evaluation records with explicit reflex grading or Spurling test documentation.

---

### Tweak 5 — Single Source of Truth for Gaps

**Files**: `apps/worker/steps/export_render/timeline_pdf.py`, `appendices_pdf.py`

**Problem**: The snapshot gap summary on Page 1 used three different gap sources (`lsv1_gap_gt45`, `global_gaps`, `raw_gaps_gt45`) while Appendix C read from `missing_records.gaps`. This caused inconsistency where Page 1 said "171-day gap documented" but Appendix C said "No treatment gaps detected."

**Fix**: Both the snapshot summary and Appendix C now read exclusively from `extensions.missing_records.gaps` (the pipeline's single computed gap list). A gap is displayed if `gap_days > 0`.

**Observed output** (batch029):
- Appendix C1 (Gap Boundary Anchors): `Gap: 2025-05-29 to 2025-11-16 (171 days)`
- Appendix C (Treatment Gaps): `- 2025-05-29 to 2025-11-16 (171 days)`

Both sections now show the same gap with the same dates. ✅

---

### LLM Policy

**Files**: `apps/worker/pipeline.py`, `scripts/eval_sample_172.py`, `packages/shared/models/domain.py`, `apps/worker/lib/artifacts_writer.py`, `AGENTS.md`

**Change**: MEDIATION export mode permanently disables LLM reasoning (`config.enable_llm_reasoning = False`) before any pipeline step runs. Both the production pipeline (`pipeline.py`) and the eval pipeline (`eval_sample_172.py`) enforce this.

A new `llm_polish_applied` boolean is written to `evidence_graph.extensions` for auditing:
- `false` — LLM was disabled (always the case for MEDIATION)
- `true` — LLM ran and succeeded
- `false` — LLM was enabled but threw an exception (fail-safe)

Two new `RunConfig` fields were added:
- `enable_llm_for_mediation: bool = False` — permanently False; guards against accidental enablement
- `llm_polish_internal: bool = True` — INTERNAL exports may use LLM

**Observed output**:
```json
"llm_polish_applied": false
```
Confirmed in both batch029 and 05_minor_quick evidence graphs. ✅

---

## Test Results

| Test suite | Before Pass34 | After Pass34 |
|------------|---------------|--------------|
| `test_mediation_sections.py` (77 tests) | 77 passed | 77 passed |
| Overall unit suite | 37 failed (pre-existing) | 37 failed (pre-existing, no change) |
| Gold harness 05_minor_quick MEDIATION | — | ✅ pass, parity=true |
| Gold harness batch029 MEDIATION | — | ✅ pass, parity=true |

All 3 tests that failed immediately after implementing Tweak 4 (adding `neuro_deficits` as 11th section) were fixed by updating `_EXPECTED_ORDER` and the count assertion in `test_mediation_sections.py`. The 37 pre-existing failures are unrelated to Pass34 (rooted in `top10_manifest_only=True` and other pre-existing conditions).

---

## Artifacts

| File | Description |
|------|-------------|
| `05_minor_quick/output_MEDIATION.pdf` | MEDIATION PDF for simple soft-tissue MVC case |
| `05_minor_quick/evidence_graph.json` | Evidence graph (llm_polish_applied=false) |
| `05_minor_quick/gold_summary.json` | Deterministic parity summary |
| `batch029/output_MEDIATION.pdf` | MEDIATION PDF for complex prior-injury spine case |
| `batch029/evidence_graph.json` | Evidence graph (llm_polish_applied=false, 2 gaps) |
| `batch029/gold_summary.json` | Deterministic parity summary |

---

## Observations and Notes

1. **Neuro section requires structured exam data**: The new `neuro_deficits` section relies on `exam_findings` being populated with structured neuro findings. Both test packets had empty `exam_findings` arrays — the neurological data was present in raw citation text but not extracted into structured fields. The section will activate when the pipeline produces richer exam extraction.

2. **Negative imaging in timeline vs. mediation sections**: The Tweak 2 filter applies only to the mediation leverage brief's OBJECTIVE FINDINGS section. The full medical timeline table still shows all events including "Unremarkable lumbar spine series" — intentional, as the timeline is the factual record for citation purposes.

3. **"C2-C3: Normal disc signal and height. No canal stenosis."** — This finding (batch029, page 3) was NOT filtered by Tweak 2 because "normal disc signal" and "no canal stenosis" do not match the noise pattern. This is correct: documenting the absence of stenosis at specific levels is clinically meaningful for a radiculopathy case.

4. **Gap consistency confirmed** (batch029): The 171-day gap (2025-05-29 to 2025-11-16) now appears identically in both Appendix C1 (gap boundary anchors) and Appendix C (treatment gaps). The pre-Pass34 inconsistency is resolved.

5. **llm_polish_applied initially missing from MEDIATION output**: The `artifacts_writer.py` allowlist was filtering `llm_polish_applied` out of MEDIATION evidence graphs. Fixed by adding it to `_MEDIATION_EXTENSION_ALLOWLIST`. This is a debugging/audit signal, not a valuation field.
