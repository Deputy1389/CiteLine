# CiteLine Roadmap

> Freeze the spine, expand the ribs.  
> Spine: PDF → Pages → Segments → Providers → Events → Citations → Evidence Graph → Artifacts

## Invariants (never break these)

1. Every Event has ≥1 `citation_id` (or explicit flag)
2. Every Citation references an existing `page_id`
3. Provider entities are deduped deterministically (stable normalization)
4. Evidence Graph is deterministic and JSON-serializable
5. New fields go under `extensions.*` unless foundational primitives
6. Schema root includes `schema_version` (additive)
7. Existing API routes/fields never rename or remove

## What NOT To Do

- Rewrite the pipeline spine
- Add a UI layer (graph is source of truth)
- Touch DB migrations unless strictly necessary
- Implement demand drafting, depo prep, or specials calculation prematurely
- Add non-deterministic extraction (LLM) without a separate flag

---

## Phase 0: Stabilize Extraction Quality ✅

- Date extraction overhaul (ordinal, DD-Month-YYYY, anchor, relative, propagation)
- Extraction hardening: dateless events emitted with `MISSING_DATE` flag
- `SkippedEvent` debug records in evidence graph
- Provider candidate filtering (sentence rejection, length bounds)

## Phase 1: Graph Normalization 🔧

- Add `schema_version` to `EvidenceGraph`
- Introduce `extensions` namespace on `EvidenceGraph`
- ProviderEntity normalization: enhanced dedupe with credential stripping, first/last seen dates, event counts
- CoverageSpan computation per provider stored under `extensions.coverage_spans`

## Phase 2: Provider Directory Artifact 🔧

- Generate `provider_directory.csv` and `provider_directory.json` from graph data
- Columns: display name, type, first seen, last seen, event count, citation count
- Save alongside existing chronology artifacts
- Register in DB + expand API whitelist

## Phase 3: Missing Record Detection ⏳

- Analyse coverage spans for gaps in expected treatment
- Generate missing-record report artifact
- No new extraction — purely graph-derived

## Phase 4: Billing Primitives ⏳

- Extract CPT/ICD codes into `extensions.billing_lines`
- Structure for later Specials calculation

## Phase 5: Specials Aggregation ⏳
## Phase 6+: Demand Draft / Depo Prep ⏳
## Phase 7+: Production Hardening ⏳
## Phase 8+: Optional UI ⏳
