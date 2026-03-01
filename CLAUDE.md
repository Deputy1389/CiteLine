# CiteLine — Claude Instructions

Read `agents.md` in this repo root before making any changes. It contains the full product
context, architectural rules, deployment map, and checklists that apply to all work here.

## What This Is

CiteLine converts raw medical PDF packets into citation-anchored, demand-ready chronologies
for personal injury lawyers. Data accuracy is existential — one wrong date or contradictory
visit count loses the client. Every claim must be tied to a source page citation.

## Non-Negotiable Rules (Short Version)

1. **Renderer is keyword-free.** No medical keywords in `timeline_pdf.py`, `common.py`, or
   anything under `export_render/`. Clinical logic belongs in the pipeline, not the renderer.

2. **Pipeline ranks, renderer formats.** The renderer displays what the pipeline provides in
   the order the pipeline provides it. It never re-ranks or re-extracts.

3. **Config must flow.** No hardcoding values that belong in `RunConfig`. No overwriting config
   after it is loaded from the DB. Check that `CreateRunRequest` defaults match `RunConfig` defaults.

4. **JSON columns use `.model_dump()`.** Never `.model_dump_json()` for SQLAlchemy JSON columns.
   Never call `json.loads()` on a value already read from a JSON column.

5. **Text quality runs first.** CID font garbage (`(cid:123)`) and OCR noise must be detected
   and handled before provider detection and event extraction.

6. **Works for all case types.** MVA/spine, shoulder, TBI, knee, workers comp, slip and fall.
   Never assume a specific injury type. If logic is injury-specific, it belongs in the pipeline
   as typed structured data, not as keyword lists in the renderer.

7. **`evidence_graph.json` is the `EvidenceGraph` object directly** — not wrapped in
   `ChronologyResult`. The frontend reads `payload.events` and `payload.extensions` at top level.

## Output Is Not Done Until

- No placeholder text on Pages 1–5 (`1900-01-01`, `Unknown provider`, `Not available`)
- Visit counts consistent across snapshot, timeline, and treatment pages
- Every attorney-facing claim has a page citation
- Billing is either accurate or clearly flagged as incomplete

## Full Context

See `agents.md` for deployment map, systemic patterns, file index, checklists, and known risks.
