# Pass 055 — Workspace Actions & Export Layer

**Date:** 2026-03-05
**Scope:** Wire the stub buttons in the Pass 054 workspace into real functionality
**Repos in play:** `C:\Citeline` (backend/API) · `C:\Eventis\Website` (frontend)
**Theme:** Turn the workspace from a read-only intelligence display into an action platform

---

## What Was Deferred from Pass 054

From the Pass 054 plan:

| Item | Status |
|---|---|
| Demand Builder (editable sections, LLM narrative) | Stub card in Tab 6 |
| Mediation Packet export (PDF + Word) | Stub card in Tab 6 |
| `Play case` animation polish | Partial in Tab 1 |
| Deposition suggested questions (LLM generation) | Stub text in Tab 6 |
| Evidence anchor overlay (reverse lookup: page → claims) | Not started |
| Case-to-case comparison view | Not started |
| PDF pixel-perfect bounding box highlights (coordinate mapping) | Not started |
| Backend `/matters/{matterId}/workspace` typed endpoint | Still raw JSON proxy |

---

## Objective

Three deliverables in priority order:

### 1. Demand Builder (highest value, Tab 6)
Attorney can generate a structured demand narrative from the evidence graph. Sections are editable before export.

### 2. Mediation Packet Export (Tab 6)
Re-use existing `mediation_sections.py` pipeline output. Render it in-browser and let the attorney download as PDF.

### 3. Evidence Anchor Overlay (Tab 2 / PDF Viewer)
"Reverse lookup" — when viewing a PDF page, show all workspace claims that cite it. Turns the PDF viewer into a bi-directional evidence navigator.

---

## Architecture Decisions

### A. Demand Builder
- **Backend**: New API endpoint `POST /matters/{matterId}/demand-narrative` — calls Claude Sonnet via the Anthropic SDK, passing injury clusters + causation timeline + settlement posture as context. Returns structured sections: `{ liability, injuries, treatment, specials, demand_amount }`.
- **Frontend**: Editable text areas per section, markdown-rendered preview on the right. "Download as PDF" generates a styled PDF via browser print dialog (no server-side PDF generation needed for v1).
- **LLM model**: `claude-sonnet-4-6` — fast enough for interactive use, smart enough for legal narrative.

### B. Mediation Packet Export
- The worker already generates `mediation_sections` in the evidence graph (`extensions.mediation_sections` or via the mediation export step).
- Pass 055 wires the existing data into a styled in-browser render (HTML → print CSS → PDF via browser).
- No new backend work needed — data is already there.

### C. Evidence Anchor Overlay
- Build a reverse index at adapter time: `pageIndex: Map<pageNumber, CitationRef[]>`.
- In the PDF viewer, after a page renders, show a small badge `3 claims` over the page margin.
- Clicking the badge opens the Evidence Trace panel pre-populated with all claims on that page.

### D. Backend Workspace Endpoint (optional, defer again if time-constrained)
The raw JSON proxy via `evidence_graph.json` artifact download works fine. A typed `/workspace` endpoint is a performance optimization (smaller payload, no frontend adapter needed) but not blocking anything. Can defer to Pass 056.

---

## Implementation Plan

### Phase 1 — Demand Builder

**1.1 Backend endpoint**

File: `apps/api/routes/matters.py` (or create `apps/api/routes/demand.py`)

```python
POST /matters/{matter_id}/demand-narrative
```

Request body:
```json
{
  "run_id": "abc123",
  "tone": "aggressive|moderate|conservative",
  "section": "liability|injuries|treatment|specials|demand_amount|null"
}
```

`section` is optional. If omitted, all five sections are generated. If provided, only that section is (re)generated and merged into the existing draft.

Reads evidence graph from the run's artifact, passes key sections to Claude, returns:
```json
{
  "draft_id": "uuid",
  "sections": {
    "liability":     { "text": "...", "citations": [...] },
    "injuries":      { "text": "...", "citations": [...] },
    "treatment":     { "text": "...", "citations": [...] },
    "specials":      { "text": "...", "citations": [...] },
    "demand_amount": { "text": "...", "citations": [...] }
  }
}
```

When `section` is provided, the response only includes that one section and the backend merges it into the stored draft record before returning.

LLM prompt structure:
- System: "You are a personal injury attorney drafting a demand letter. Write factually — every claim must be traceable to the evidence provided. No speculation."
- User: Structured JSON of `injury_clusters`, `causation_timeline`, `settlement_leverage_model`, `billing_summary`. When regenerating a single section, include only the context relevant to that section (e.g. `injury_clusters` for injuries, `billing_summary` for specials).
- Output: JSON with section text + cited claim IDs.

**1.1b Draft persistence endpoint**

```python
GET  /matters/{matter_id}/demand-drafts           # list drafts for this matter
GET  /matters/{matter_id}/demand-drafts/{draft_id} # load a specific draft
PATCH /matters/{matter_id}/demand-drafts/{draft_id} # save edited section text
```

The `POST /demand-narrative` endpoint auto-creates a draft row on first generation and updates it on section regeneration. The frontend loads the latest draft on mount — no work is lost on refresh.

**1.2 Frontend — DemandBuilderTab (replaces stub in Tab 6)**

File: `C:\Eventis\Website\components\workspace\DemandBuilderTab.tsx`

Layout:
```
┌─────────────────────┬──────────────────────────┐
│ SECTION NAV         │  SECTION EDITOR           │
│                     │                           │
│ • Liability    [↺]  │  [editable text area]     │
│ • Injuries     [↺]  │  [citation chips]         │
│ • Treatment    [↺]  │                           │
│ • Specials     [↺]  │  ─────────────────────    │
│ • Demand Amt   [↺]  │  PREVIEW (markdown)       │
│                     │                           │
│ [Generate All]      │  [Download PDF] button    │
└─────────────────────┴──────────────────────────┘
```

Tone selector: `Aggressive | Moderate | Conservative` (radio buttons in top bar).

Per-section regenerate UX:
- Each section item in the left nav has a small `↺` icon button.
- Clicking it calls `POST /demand-narrative` with `{ section: "injuries" }` — only that section is regenerated.
- While regenerating, that section's nav item shows a spinner; other sections remain editable.
- After response, the section text updates in place and the draft is auto-saved.
- The attorney never loses other sections while tweaking one.

Draft persistence UX:
- On mount, the component calls `GET /demand-drafts` for this matter.
- If a draft exists for the current run, it loads automatically — the attorney picks up where they left off.
- All text edits auto-save via debounced `PATCH /demand-drafts/{draft_id}` (500ms debounce).
- A subtle "Saved" indicator in the top bar confirms persistence.
- Multiple drafts per matter are supported (list shows timestamps); attorney can switch between them.

**1.3 API routes (frontend proxies)**

Files:
- `app/api/citeline/matters/[matterId]/demand-narrative/route.ts` — POST (generate/regenerate)
- `app/api/citeline/matters/[matterId]/demand-drafts/route.ts` — GET (list), POST (create)
- `app/api/citeline/matters/[matterId]/demand-drafts/[draftId]/route.ts` — GET (load), PATCH (save edits)

**1.4 Database — `draft_demands` table**

```sql
CREATE TABLE draft_demands (
  id          TEXT PRIMARY KEY,        -- uuid
  case_id     TEXT NOT NULL,           -- matter_id
  run_id      TEXT NOT NULL,           -- FK → runs.id
  sections    JSONB NOT NULL,          -- { liability, injuries, treatment, specials, demand_amount }
  tone        TEXT NOT NULL DEFAULT 'moderate',
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_draft_demands_case_id ON draft_demands(case_id);
```

Add to `packages/db/models.py` as `DraftDemand` SQLAlchemy model.
Add migration script to `scripts/` (run once on Supabase).

---

### Phase 2 — Mediation Packet Export

**2.1 Read mediation data from evidence graph**

The `extensions.mediation_sections` key (if present) or fallback to constructing from:
- `extensions.settlement_model_report`
- `extensions.defense_attack_map`
- `extensions.causation_timeline_registry`

**2.2 Frontend — MediationPacketTab (replaces stub in Tab 6)**

File: `C:\Eventis\Website\components\workspace\MediationPacketTab.tsx`

Renders a styled, print-ready HTML view of the mediation packet sections.
- "Download PDF" button triggers `window.print()` scoped to the packet element.
- Print CSS hides the workspace chrome, shows only the packet content.

---

### Phase 3 — Evidence Anchor Overlay

**3.1 Reverse citation index in adapter**

In `workspace-adapter.ts`, after building `citations: Map<string, CitationRef>`, also build:
```typescript
pageIndex: Map<number, CitationRef[]>  // page_number → citations on that page
```

Add `pageIndex` to `CaseWorkspacePayload`.

**3.2 Badge overlay in RecordViewer**

In `RecordViewer.tsx`, after a page renders:
- Look up `pageIndex.get(currentPage)` from context.
- If entries exist, render a small `n claims` badge in the top-right corner of the page.
- Clicking the badge fires `setTrace()` with all claims on that page (use the first, show count).

**3.3 Reverse lookup panel in EvidenceTracePanel**

When triggered from the page badge (not a single claim click), show a list mode:
```
PAGE 63 — 3 CLAIMS

1. AC joint separation · Valley Radiology
2. Rotator cuff tear · MRI Report
3. Impingement syndrome · Ortho Note
```

---

## File Checklist

### C:\Citeline (backend)

- [ ] `apps/api/routes/demand.py` — full demand CRUD:
  - `POST /matters/{id}/demand-narrative` — generate all or single section (optional `section` param)
  - `GET  /matters/{id}/demand-drafts` — list drafts for matter
  - `GET  /matters/{id}/demand-drafts/{draft_id}` — load draft
  - `PATCH /matters/{id}/demand-drafts/{draft_id}` — save edited section text
- [ ] Register routes in `apps/api/main.py`
- [ ] Claude SDK call — full generation and per-section regeneration paths
- [ ] `packages/db/models.py` — `DraftDemand` SQLAlchemy model
- [ ] `scripts/migrate_draft_demands.py` — create `draft_demands` table in Supabase

### C:\Eventis\Website (frontend)

- [ ] `lib/workspace-types.ts` — add `pageIndex: Map<number, CitationRef[]>` to `CaseWorkspacePayload`
- [ ] `lib/workspace-adapter.ts` — build `pageIndex` during adaptation
- [ ] `components/workspace/DemandBuilderTab.tsx` — full implementation with per-section `↺` regenerate + auto-save
- [ ] `components/workspace/MediationPacketTab.tsx` — full implementation
- [ ] `components/workspace/RecordViewer.tsx` — add page badge overlay
- [ ] `components/workspace/EvidenceTracePanel.tsx` — add list mode for page-level anchor
- [ ] `components/workspace/PrepPackTab.tsx` — replace stub cards with DemandBuilderTab and MediationPacketTab
- [ ] `app/api/citeline/matters/[matterId]/demand-narrative/route.ts` — POST proxy
- [ ] `app/api/citeline/matters/[matterId]/demand-drafts/route.ts` — GET/POST proxy
- [ ] `app/api/citeline/matters/[matterId]/demand-drafts/[draftId]/route.ts` — GET/PATCH proxy

---

## Quality Gates

- [ ] Demand narrative generates in < 15 seconds for a real case
- [ ] Every generated section contains at least one citation chip
- [ ] Mediation packet PDF prints cleanly with no workspace UI chrome
- [ ] Evidence anchor badges appear on pages that have citations in the loaded evidence graph
- [ ] Clicking a page badge populates the Evidence Trace panel correctly
- [ ] No hardcoded injury types or case assumptions in the demand LLM prompt
- [ ] Tone selector changes the LLM system prompt (not just the label)
- [ ] Download PDF works in Chrome, Firefox, Safari

---

## Deferred to Pass 056

- Case-to-case comparison view
- PDF pixel-perfect bounding box highlights (coordinate mapping from PDF.js)
- Backend `/matters/{matterId}/workspace` typed endpoint (replaces raw artifact download)
- "Play case" animation polish in Case Map
- Deposition suggested questions (LLM generation)
