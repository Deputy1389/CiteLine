\
# Claude Code Build Prompt — CiteLine MVP (PI Chronology + Audit-ready foundation)

You are Claude Code operating in a Windows dev environment. Build a production-grade MVP for **CiteLine**, a bolt-on SaaS tool for small US personal injury (PI) law firms that generates **citeable medical chronologies** from uploaded PDFs.

## Hard constraints / scope
- Build only the **chronology MVP** (no demand drafting, no legal advice, no valuation).
- Output must be **auditable**: every extracted fact must include **citations** (page + snippet; bbox best-effort).
- The core extraction pipeline must be **deterministic** (rules/heuristics). If you use any LLM, it must be **optional** and never the only path.
- Design must be **Audit add-on ready** later (missing evidence / readiness report) by storing structured evidence graph objects.
- Do NOT integrate with Clio/Filevine.
- Do NOT build a full platform UI. A minimal API and worker are sufficient.

## Repo / folder context
- Work in: `C:\CiteLine\`
- I have a utility folder copied from ClearCase: `C:\CiteLine\Clearcase utility\` containing uploads + OCR helpers. Reuse these rather than re-inventing.
  - Treat those helpers as stable primitives.
  - If dependencies are missing, copy minimal required utilities into `packages/shared/`.

## Deliverables
1) A monorepo with:
   - `apps/api`
   - `apps/worker`
   - `packages/db`
   - `packages/shared`
   - `schemas/pi-chronology-mvp.schema.json` (provided)
   - `docs/pi-chronology-mvp.pipeline.md` (provided)

2) Minimal endpoints:
   - `POST /firms` create firm
   - `POST /firms/{firm_id}/matters` create matter
   - `POST /matters/{matter_id}/documents` upload PDF (multipart)
   - `POST /matters/{matter_id}/runs` start processing (enqueue background job)
   - `GET /runs/{run_id}` run status + metrics
   - `GET /matters/{matter_id}/exports/latest` returns artifact paths (PDF/CSV/JSON)

3) Worker pipeline implementing `docs/pi-chronology-mvp.pipeline.md` in order, producing a JSON output that validates against `schemas/pi-chronology-mvp.schema.json`.

4) Export generation:
   - PDF chronology
   - CSV chronology
   - JSON evidence graph

5) Run receipts:
   - Store a `RunRecord` with metrics, warnings, provenance, input/output hashes.
   - Idempotency: if the same document sha256 is reprocessed with same config, allow cache reuse.

## Production-grade design requirements
- Clear separation of concerns: API (I/O), Worker (processing), DB (persistence), Shared (types/schema).
- Strong validation (Pydantic/Zod/etc).
- Deterministic extraction rules (no hallucinated facts).
- Observability: structured logs + persisted metrics/warnings.
- Security posture (MVP): no training on customer data; retention policy recorded; artifacts not public.

## Implementation details (follow these)
### A) Data model (DB)
Implement tables/entities aligned with the schema:
- Firm, Matter, SourceDocument, Run
- Provider, Document, Page, Event, Citation, Gap, Artifact

Use migrations. Keep it simple.

### B) Storage (MVP)
Store uploaded PDFs and generated artifacts on local disk:
- `C:\CiteLine\data\uploads\{source_document_id}.pdf`
- `C:\CiteLine\data\artifacts\{run_id}\chronology.pdf|.csv|.json`

Store `storage_uri` as a local path for now.

### C) Pipeline
Implement the deterministic pipeline steps in `docs/pi-chronology-mvp.pipeline.md`.
Non-negotiables:
- embedded text first; OCR fallback once
- rule-based page type classification
- no Event without citations
- PT default aggregation
- billing events stored even if not exported
- confidence scoring + export thresholding

### D) PDF generation
Generate a clean PDF:
- Title page: "CiteLine Chronology" + matter title + run id + timestamp
- Disclaimer: "Factual extraction with citations. Requires human review."
- Event blocks:
  - Date | Provider | Type
  - Bullet facts with "p. X" refs
- Appendix: gaps list

### E) Schema validation
Validate JSON output against `schemas/pi-chronology-mvp.schema.json`.
If validation fails, mark run `partial` and store warnings; still emit artifacts when possible.

## Acceptance tests (must add)
- Unit tests for classifier, date tiering, provider normalization, de-dup, confidence scoring
- Integration test with a synthetic PDF fixture ensuring:
  - ≥1 event
  - every event has ≥1 citation
  - JSON validates

## Step-by-step plan (execute in this order)
1. Scaffold monorepo folders.
2. Choose stack (recommend Python FastAPI + worker in Python for speed).
3. Implement DB + migrations.
4. Implement upload + store PDF locally + sha256 hashing.
5. Implement worker pipeline end-to-end.
6. Implement API endpoints for matter/docs/runs/exports.
7. Add tests; ensure they pass.
8. Add README with setup + run + curl examples.

Do not overbuild. Ship the deterministic engine + clean interfaces.
