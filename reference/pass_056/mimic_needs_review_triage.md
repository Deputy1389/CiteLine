# Pass 056 MIMIC Needs-Review Triage

Date: 2026-03-05 PST / 2026-03-06 UTC

## Scope

Fresh cloud reruns triaged:
- `814928e206ff49a2a1af743148213921` (`Patient_10000032.pdf`)
- `beafbdd2562243ee802609a02c1668e6` (`Patient_10001217.pdf`)
- `9f6dabdc56ba438f95c72dd526f3e4bf` (`Patient_10002428.pdf`)

All three terminated as `needs_review`.

## Primary Cause Shared By All Three

### 1. Litigation reviewer `Q2` is a format-based coverage gate, not a validity gate

File:
- `apps/worker/lib/litigation_review.py:218`

Code:
- `q2_pass = len(self.data['events']) > 5 if self.data['events'] else len(self.text_content) > 1000`

Observed impact:
- Run `814928e206ff49a2a1af743148213921`: `1` event, `21` citations
- Run `beafbdd2562243ee802609a02c1668e6`: `1` event, `16` citations
- Run `9f6dabdc56ba438f95c72dd526f3e4bf`: `2` events, `44` citations
- All three passed hard invariants and failed `Q2` only.

Assessment:
- This is a false-positive gate for compact but valid packets.
- The MIMIC summaries are short-form admission/discharge packets. Requiring `>5` events is another hidden prose/volume proxy.

Recommended refactor:
- Replace count-only `Q2` with a policy gate based on evidence sufficiency, for example:
  - pass if there is at least one citation-anchored substantive event and no hard invariant failure
  - score using evidence density per page, anchored claim count, and chronology coherence
  - treat compact single-admission packets as valid if citation-backed, not auto-suspicious

## Real Defect Found During Triage

### 2. Paralegal chronology payload injects hardcoded shoulder/gunshot milestones into unrelated packets

File:
- `apps/worker/steps/step18_paralegal_chronology.py:144`

Code:
- `_inject_required_milestones()` hardcodes:
  - `05/07/2013` ORIF + rotator cuff repair + bullet removal
  - `05/21/2013` wound irrigation/debridement and infection management
  - `10/10/2013` hardware removal + rotator cuff repair + debridement
  - `01/21/2014` follow-up encounter

Observed impact:
- All three MIMIC evidence graphs contain unrelated 2013/2014 chronology entries with citation `Source chronology section`.
- This contaminates:
  - `reference/run_814928e206ff49a2a1af743148213921_evidence_graph.json:3056`
  - `reference/run_beafbdd2562243ee802609a02c1668e6_evidence_graph.json:3012`
  - `reference/run_9f6dabdc56ba438f95c72dd526f3e4bf_evidence_graph.json:5053`

Assessment:
- This is a real cross-packet contamination bug, not a strictness issue.
- It likely should force `needs_review`, because it introduces contradictory uncited chronology into the artifact contract.

Recommended refactor:
- Remove `_inject_required_milestones()` entirely from production path.
- If it exists for eval/golden support, isolate it behind explicit test-only code.
- Add a regression test asserting no synthetic/default chronology entries are emitted when the packet lacks those records.

## Secondary Output Quality Issues

### 3. Output still contains non-attorney-safe placeholder-style fallbacks

Files:
- `apps/worker/steps/export_render/timeline_pdf.py:1913`
- `apps/worker/steps/export_render/timeline_pdf.py:1979`
- `apps/worker/steps/export_render/timeline_pdf.py:1983`

Observed output examples from saved PDFs:
- `Patient name not reliably extracted from packet`
- `Injury mechanism is not expressly documented in chart notes.`
- `Readiness Tier: Action Required`

Assessment:
- For INTERNAL analytics mode, these may be acceptable diagnostics.
- For litigation-safe export standards in `AGENTS.md`, these are still placeholder/diagnostic language and should not graduate to attorney-facing success.
- These do not explain the shared `Q2` failure, but they do support `needs_review` as a status for these runs.

Recommended refactor:
- Keep these as internal diagnostics only.
- Ensure exportable/attorney-facing modes suppress or transform them into explicit incompleteness disclosures that satisfy the revenue-critical invariant rules.

## What Pass 056 Did Prove

- Future-dated MIMIC content no longer crashes date extraction on cloud.
- Structured lab rows survive extraction and rendering.
- Runs degrade to `needs_review` instead of failing outright.

## What Still Needs Follow-up

1. Replace litigation-review `Q2` with evidence-based coverage logic.
2. Remove hardcoded paralegal chronology milestone injection from production.
3. Re-run the same three MIMIC packets after those two fixes.
