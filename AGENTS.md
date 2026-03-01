# CiteLine: Agent Guidelines

This file is the authoritative context for every agent working in this repo.
Read it fully before making any changes.

---

## What This Product Is

CiteLine is a medical record engine for personal injury law firms.

PI lawyers receive hundreds of pages of raw medical PDFs — hospital records, imaging reports,
PT notes, billing statements — and must manually build a chronology to use in mediation or demand.
That process takes paralegals 3–6 hours per case.

CiteLine automates it. The pipeline ingests the PDF packet, extracts every clinical encounter,
anchors each finding to a source page citation, and exports a demand-ready chronology PDF the
attorney can use in 10 minutes.

**The product's value rests on four things:**
1. Every claim is tied to a source page. No hallucinations, no unsupported statements.
2. The output is defensible in mediation — the defense cannot challenge what is directly cited.
3. It saves a paralegal a half-day of work per case.
4. It elevates the strongest objective findings automatically — the attorney sees what matters first.

If the output has a wrong date, a missing provider, a `1900-01-01`, or a visit count that
contradicts itself in two places, the attorney loses trust and cancels. Data accuracy is not
a quality concern — it is the product.

---

## Who Uses This and What They Need

**Primary user: PI attorney or paralegal**

They open the exported PDF and need to see:
- A clean date-ordered timeline of every medical encounter
- Key objective findings (imaging pathology, weakness, deficits, injury-specific findings) on the front page
- Total PT visits and date span
- Specials (total medical charges, per-provider breakdown)
- Any gaps in care flagged (defense attacks gaps — we surface them first)
- Every claim cited to a page number they can verify

**What they cannot tolerate:**
- Placeholder text ("Not available", "Unknown provider", "1900-01-01")
- Visit counts that disagree between sections
- Findings that appear in the appendix but not the front page
- Billing totals that are wrong or misleading
- A blank audit page with no events

**Case types served:**
- MVA / spine (most common — cervical, lumbar, disc, radiculopathy)
- Shoulder injuries
- TBI / concussion
- Knee injuries
- Workers compensation
- Slip and fall

The pipeline and renderer must work for all of these. Logic that only works for spine cases
is a bug, not a feature.

---

## The Core Output (What "Done" Looks Like)

A completed run produces a demand-ready PDF with:

| Page | Content |
|------|---------|
| 1 | Case snapshot: DOI, mechanism, injuries, objective findings, treatment duration, specials |
| 2 | Citation-anchored medical timeline (every row has a page citation) |
| 3 | Imaging & objective findings (grouped, citation-backed) |
| 4 | Treatment summary (PT volume, phases, compliance, discharge) |
| 5 | Billing & specials (completeness-gated — no misleading totals) |
| Appendix | Full citation index |

The `evidence_graph.json` artifact powers the audit/review UI in the frontend.

---

## Attorney Value Hierarchy (Mandatory Elevation Order)

If citation-backed findings exist anywhere in the packet, they must be elevated to Page 1
(Case Snapshot) in this order. The pipeline populates `renderer_manifest.promoted_findings`
in this priority. The renderer displays what it receives — it never re-ranks.

1. Objective neurological or functional deficits (e.g., documented weakness, range-of-motion loss)
2. Structural imaging pathology (fractures, displacement, nerve compression, tissue damage)
3. ICD-10 injury diagnoses
4. Injections or surgeries
5. Treatment duration
6. Total visit counts
7. Symptom reporting

**A qualifying finding that exists in extraction but is absent from Page 1 is an elevation bug.**
Appendix presence without Snapshot presence = pipeline failure, not a display issue.

---

## Cross-Repo Frontend Location (Production UI)

- The production `www.linecite.com/app` frontend (Command Center / review UI) is in `C:\eventis\website`.
- When debugging routes like `/app/cases/:id/review`, check `C:\eventis\website` first (not `C:\Citeline\apps/ui`).
- `C:\Citeline\apps/ui` is a separate frontend and may not match production behavior.

---

## Repo Boundaries (Read Before Patching)

- `C:\Citeline` owns worker pipeline, API routes, shared models, persistence, and artifact generation.
- `C:\eventis\website` owns the production web UI used on `www.linecite.com/app/*`.
- If a bug is visible on `linecite.com`, identify the failing layer first (worker vs API vs production frontend) before changing code.

---

## Deployment Map

- Render/API deploys from the web/backend repo and can change endpoint behavior without touching the worker host.
- Oracle worker runs separately and typically needs manual update + restart after worker code changes.
- After worker changes, verify the running worker commit before testing new uploads.

Common worker commands (Oracle):

```bash
ssh -i "C:\Users\paddy\.ssh\oracle-worker" ubuntu@192.9.156.165
cd ~/citeline && git pull
sudo systemctl restart linecite-worker
sudo journalctl -u linecite-worker -f
```

---

## The 4 Systemic Patterns (Must Read)

These are the root causes of most recurring issues. When something breaks, check these first.

### 1. Pipeline Fragmentation

Problem: Multiple pipeline entry points with different quality gates.

| Entry Point | Quality Gates |
|-------------|---------------|
| `apps/worker/pipeline.py:run_pipeline()` | Production |
| `scripts/run_case.py:run_case()` | Eval |

Rule: Any fix must apply to both entry points, or production must intentionally own the canonical behavior.

### 2. Config Doesn't Flow

Problem: Settings are added to `RunConfig` but overwritten or ignored before the pipeline uses them.

Rule: When adding config fields, ensure `CreateRunRequest` defaults and `RunConfig` defaults match,
confirm API passthrough persists the field, and confirm no pipeline step overwrites it afterward.
Do not hardcode values that belong in config.

### 3. SQLAlchemy JSON Type Mismatches

Problem: Writing strings vs dicts to JSON columns causes silent corruption or runtime 500s.

```python
# WRONG - writes string, json.loads() on it later will fail
run_row.metrics_json = model.model_dump_json()

# RIGHT - writes dict, SQLAlchemy JSON column reads it back as dict
run_row.metrics_json = model.model_dump()
```

Rule: Use `.model_dump()` for JSON columns. Never call `json.loads()` on a value from a JSON column —
SQLAlchemy already deserialised it.

### 4. Text Quality Too Late

Problem: Quality checks run after extraction, so OCR garbage and CID font artifacts
(`(cid:123)`) pollute provider detection, event extraction, and chronology text.

Rule: Quality filtering (CID detection, OCR fallback, garbage detection) must run before
provider detection and event extraction. Bad text in = bad output everywhere downstream.

---

## Renderer Architecture Rules (Non-Negotiable)

These rules exist because CiteLine serves all PI case types. Logic written for one case type
silently breaks others and creates permanent maintenance debt.

### Renderer is keyword-free

- `timeline_pdf.py`, `common.py`, and any file under `export_render/` must contain zero
  medical keywords (disc, radiculopathy, lumbar, cervical, fracture, rotator, TBI, meniscus, etc.)
- If a display decision requires knowing the injury type, that decision belongs in the pipeline.
- Violation: scanning snippet text for "radiculopathy" to decide what shows on Page 3.
- Correct pattern: read `manifest.promoted_findings`, display what the pipeline provided.
- Code review rule: any medical keyword list added to renderer files should be removed and
  replaced with a pipeline-side structured field.

### Pipeline ranks, renderer formats

- Clinical prioritization (objective deficit > diagnosis > imaging > symptom) lives in pipeline steps only.
- The renderer receives an ordered list and renders it in order. It never re-ranks.
- If ranking logic appears in the renderer, move it upstream to the pipeline.

### RendererManifest is the contract

- The pipeline emits a `RendererManifest` stored in `evidence_graph.extensions["renderer_manifest"]`.
- The renderer reads typed fields from the manifest. It does not re-parse `evidence_graph` internals.
- Key manifest fields: `doi`, `mechanism`, `pt_summary`, `promoted_findings`,
  `top_case_drivers`, `billing_completeness`.
- If the manifest is absent, renderer falls back to existing behavior — never to keyword scanning.
- Full spec: `reference/pdf_renderer_data_elevation_plan.txt`

### Case-type agnostic by default

- Any pipeline or renderer change must work for all PI case types: MVA/spine, shoulder, TBI,
  knee, workers comp, slip and fall.
- Before finishing any change, ask: "Does this logic assume a specific injury type?"
  If yes, restructure so the pipeline provides that information as typed data.
- Tests must cover at least two different case types. See Golden Packets below.

---

## Output Quality Standard

A run is attorney-ready when:

1. Every claim on Pages 1–5 has a page citation the attorney can verify
2. No placeholder text is visible ("Not available", "Unknown provider", "1900-01-01", "undated")
3. Visit counts are consistent across all sections (snapshot, timeline, treatment page)
4. Objective findings appear on the front page if they exist anywhere in the record
5. Billing is either accurate or clearly flagged as incomplete — never silently wrong
6. Provider names are real — not "Unknown" or synthetic fallbacks

If any of these fail, the output is not shippable regardless of whether the pipeline completed
successfully.

---

## Revenue-Critical Invariants

If any of the following occur, the run **must** degrade to `needs_review` status — not `success`:

- Placeholder text visible on Pages 1–3 (`Not available`, `Unknown`, `1900-01-01`)
- Conflicting visit counts between any two sections
- Incorrect or misleading billing totals
- Any uncited statement on Pages 1–5
- Objective findings present in appendix but absent from Page 1

These are not quality warnings. They are revenue killers — an attorney who sees any of these
cancels and does not come back.

---

## Important Files

| File | Purpose |
|------|---------|
| `apps/worker/pipeline.py` | Production pipeline entry — canonical behavior |
| `apps/worker/lib/quality_gates.py` | Production quality gates wrapper |
| `apps/api/routes/runs.py` | Run API defaults + response serialization |
| `apps/api/routes/exports.py` | Latest export selection for audit/review flows |
| `packages/shared/models/domain.py` | Domain models (`RunConfig`, `RendererManifest`) |
| `packages/db/models.py` | ORM models (`Run`, `Artifact`, etc.) |
| `reference/diagnostic_prompt.md` | Troubleshooting guide |
| `reference/pdf_renderer_data_elevation_plan.txt` | Renderer architecture + RendererManifest spec |

---

## Artifact Contract (UI-Critical)

- `evidence_graph.json` is saved as the `EvidenceGraph` object directly — not wrapped in `ChronologyResult`.
- The audit/review UI fetches this artifact and reads `payload.events`, `payload.citations`,
  and `payload.extensions` at the top level.
- UI consumers depend on these `extensions` fields:
  - `claim_rows`
  - `causation_chains`
  - `case_collapse_candidates`
  - `contradiction_matrix`
  - `narrative_duality`
  - `citation_fidelity`
  - `renderer_manifest`
- If artifact shape changes, validate all three layers: worker output, API download route,
  and production frontend parsing.

---

## Status Compatibility Matrix (Do Not Forget)

When adding/changing run statuses (e.g. `needs_review`), update all of:

- DB/ORM model status handling
- API serializers / response models (`runs`, `run detail`)
- export selection endpoints (e.g. `/matters/{id}/exports/latest`)
- frontend run list/status badges
- frontend audit/review loaders (status gating for artifact fetches)

If one layer misses the new status, the symptom is a blank UI with no obvious error.

---

## Migration Discipline

- ORM model changes must be paired with a migration plan (migration file/ID or migration-safe fallback).
- If deployment order is uncertain, make writes conditional so old schemas do not break production.
- Avoid adding non-null columns in code first without confirming DB rollout timing.

---

## New Feature Checklist

- [ ] Works in production pipeline (`apps/worker/pipeline.py`)
- [ ] Works in eval path (`scripts/run_case.py`) or divergence is explicit and intentional
- [ ] Config defaults match between API (`CreateRunRequest`) and `RunConfig`
- [ ] No pipeline step overwrites config values after loading from DB
- [ ] JSON columns use `.model_dump()` (not `.model_dump_json()`)
- [ ] No `json.loads()` called on SQLAlchemy JSON column values
- [ ] Artifact schema/shape changes are reflected in API + UI consumers
- [ ] Run status handling updated everywhere (`success`, `partial`, `failed`, `needs_review`)
- [ ] Cloud smoke test completed (worker + API + UI) — not just local execution
- [ ] No medical keywords added to renderer files (`timeline_pdf.py`, `common.py`, `export_render/`)
- [ ] Change works for all case types, not just the packet currently being tested
- [ ] If renderer displays new clinical data, it reads from manifest — not from raw text scanning
- [ ] Output quality standard met: no placeholders, consistent counts, all claims cited

---

## Common Issues & First Checks

| Symptom | First Check |
|---------|-------------|
| 500s on runs endpoints | JSON column types — are you calling `json.loads()` on an already-deserialized dict? |
| Config changes do nothing | Is the config being overwritten in `pipeline.py` after loading from DB? |
| Audit/review page blank | Is `evidence_graph.json` saving the `EvidenceGraph` directly (not wrapped)? Check artifact endpoint + frontend status gating. |
| Unknown/junk providers | CID font garbage in page text — check OCR fallback fired. Text quality must run before provider detection. |
| Visit counts disagree | PT count source — is the snapshot reading a different field than the timeline? |
| Page 3 shows "Not available" | Is `promoted_findings` populated in the manifest? Are findings citation-backed? |
| Eval passes, prod fails | Pipeline fragmentation — eval path diverged from production extractor signatures. |
| Billing totals wrong | `billing_completeness` field — is it set correctly? Partial billing must not show case totals. |

---

## Cloud Validation Checklist (After Pipeline/API Changes)

- [ ] Start a fresh cloud run on a real matter
- [ ] Worker reaches terminal status (`success`, `partial`, or `needs_review`) without crashing
- [ ] `GET /api/citeline/matters/{matter_id}/runs` returns `200`
- [ ] `GET /api/citeline/matters/{matter_id}/exports/latest` returns `200` for exportable statuses
- [ ] `GET /api/citeline/runs/{run_id}/artifacts/by-name/evidence_graph.json` returns `200`
- [ ] Review/Audit UI renders non-empty case data (events visible, citations present)
- [ ] Exported PDF has no placeholder text on Pages 1–5
- [ ] Visit counts are consistent between snapshot, timeline, and treatment pages

---

## Golden Packets (Regression Set)

| Packet | Case Type | Purpose |
|--------|-----------|---------|
| `PacketIntake\\batch_029_complex_prior` | MVA / spine | Complex prior-history stress test, chronology noise |
| `PacketIntake\\05_minor_quick` | MVA / spine | Fast smoke test, gating sanity |

**Case-type coverage gap:** Both current packets are MVA/spine. Before shipping renderer or
pipeline changes, the regression set should include at least one non-spine case type.
When a shoulder, TBI, or knee packet is added, record it in this table with its case type.

Rule: Do not add case-type-specific logic to the pipeline or renderer. If logic cannot be
expressed as a generic pipeline-side typed field (e.g. a structured manifest field), it does
not belong in the renderer. A change that passes batch_029 but has never been tested on a
different injury type is not fully validated — the absence of non-spine test packets is a
test infrastructure gap, not a code permission.

---

## Coverage & Test Enforcement (Required for "Every Packet")

Architecture rules are necessary but not sufficient. "Works for every packet" must be enforced
with coverage and regression tests across packet types.

### Minimum Coverage Matrix (Expand Over Time)

Before shipping major pipeline/PDF changes, maintain regression coverage for:

- MVA/spine (complex packet)
- MVA/spine (fast smoke packet)
- At least 1 non-spine orthopedic packet (e.g. shoulder or knee)
- At least 1 neuro/TBI packet
- At least 1 procedure-heavy packet (injection/surgery)
- At least 1 sparse/incomplete billing packet
- At least 1 noisy/OCR-degraded packet

If a category is missing, document the gap and treat "all packet types" claims as unproven.

### Required Assertions Per Golden Packet

For each golden packet export, verify at minimum:

- No placeholders on Pages 1-3 (`1900-01-01`, `Unknown`, misleading `Not available`)
- No uncited statements on Pages 1-5
- Page 1 elevates qualifying findings when present in extraction/manifest
- Visit counts are consistent across Snapshot / Timeline / Treatment pages
- Billing totals are either complete and citation-backed, or explicitly incomplete
- Timeline rows are citation-anchored (no uncited rows rendered)
- Snapshot does not contradict manifest/appendix findings

### Conflict Reconciliation Rules (Must Be Tested)

When records disagree, the export must disclose the reconciliation instead of silently choosing:

- PT aggregate count conflicts (e.g. `117` vs `141`)
- DOI/date conflicts or sentinel fallback suppression
- Mechanism present in cited records but absent from summary
- Provider normalization conflicts affecting timeline display

Silent contradictions are revenue-critical failures and should degrade to `needs_review`.

### Status Gate Coverage

Add tests (unit/integration/golden validation) proving invariant failures degrade runs to
`needs_review` instead of `success`, especially for:

- placeholder text on Pages 1-3
- conflicting visit counts
- uncited statements on Pages 1-5
- objective findings present in appendix/manifest but absent from Page 1

---

## Execution Lock (Mandatory for Litigation Readiness)

For litigation-readiness work, all agents must follow:

- `reference/AgentExecutionLock.md` — one-gate-per-pass workflow, litigation-safe export gates, strict reporting format

This is the required execution contract for:

- one-gate-per-pass workflow
- acceptance-first decisioning (JSON before PDF review)
- strict reporting format
- artifact refresh requirements in `reference/`

If any instruction conflicts with ad-hoc iteration, follow `reference/AgentExecutionLock.md` unless the user explicitly overrides it in the current session.

---

## LLM Policy (Pass34)

### MEDIATION export: LLM permanently disabled

- The guard fires at **pipeline entry** (`pipeline.py`) immediately after `export_mode` is resolved —
  before any step runs. Never guard inside the renderer (too late).
- `config.enable_llm_reasoning = False` is set unconditionally when `export_mode == "MEDIATION"`.
- MEDIATION export must complete regardless of LLM quota or availability.
- `evidence_graph.extensions["llm_polish_applied"]` is set to `True`/`False` in both modes
  for unambiguous debugging.

### INTERNAL mode: LLM optional

- LLM is allowed (if available) only for: demand letter polish, associate drafting, narrative rewrite
  suggestions in INTERNAL mode.
- LLM must NOT be used for: evidence graph generation, chronology ordering, objective tier detection,
  escalation ladder, risk flag detection, gap detection, billing totals, demand multiplier math.

### Fail-safe rule

- If LLM call fails or quota exceeded: log the failure, continue with deterministic output,
  never raise or block the export.
- `llm_polish_applied: false` surfaces in evidence graph extensions.

### RunConfig fields (domain.py)

- `enable_llm_for_mediation: bool = False` — always off, never override
- `llm_polish_internal: bool = True` — optional in INTERNAL mode

### Marketing statement (unlocked by this policy)

> "No generative AI is used in mediation exports. Every statement is deterministically derived
> from cited medical records."

---

## Active Work Items (As of 2026-02-25)

These are known gaps that agents should **advance**, not work around.

- Production frontend (`C:\eventis\website`) may have status-gating drift for `needs_review` — fix in frontend, do not weaken API status handling
- Eval path (`scripts/run_case.py`) can drift from production extractor signatures — keep both paths aligned when changing extractors
- Page-quality gate thresholds are being calibrated — raise the bar, do not lower it or disable gates to reduce false positives
- LLM quota failures (`429`) degrade narrative quality; core extraction still succeeds — handle gracefully, do not let quota failures block pipeline completion
- `RendererManifest` implementation is in progress — advance it. Do not add keyword-based fallbacks or raw text scanning to the renderer while waiting for it
- Regression set is spine-only — non-spine case behavior is unverified. Do not add spine-specific assumptions; design for all case types from the start

---

## Run Status Values

- `pending` — not started
- `running` — in progress
- `success` — completed, quality passed
- `partial` — completed with schema/validation warnings
- `failed` — error during processing
- `needs_review` — completed but quality gates failed (manual review required)

---

Last updated: 2026-02-25
