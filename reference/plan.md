# Pass33 — Internal Demand Co-Pilot

**Date**: 2026-02-28
**Scope**: INTERNAL ONLY demand intelligence module. Zero mediation surface.

---

## Goal

Add a deterministic, fully explainable internal demand package to the evidence graph.
Never rendered in MEDIATION mode. Gives attorneys: demand posture, multiplier band,
single suggested anchor, negotiation strategy map, counteroffer classifier, and a
template-driven demand letter outline.

---

## 1. New File

**`apps/worker/lib/internal_demand_copilot.py`**

Public API:
```python
def build_internal_demand_package(
    evidence_graph: dict,
    csi_internal: dict | None,
    damages_structured: dict | None,
) -> dict
```

Called from `apps/worker/pipeline.py` immediately after the existing CSI/settlement
model block. Result stored at `evidence_graph.extensions["internal_demand_package"]`.

---

## 2. Strip Integration (Two Places)

### `apps/worker/lib/artifacts_writer.py`
Add `"internal_demand_package"` to `_VALUATION_EXTENSION_KEYS`.

### `apps/worker/steps/export_render/orchestrator.py`
Add `"internal_demand_package"` to `_MEDIATION_BANNED_KEYS`.

Both are defense-in-depth. The allowlist in `_MEDIATION_EXTENSION_ALLOWLIST` already
excludes it by omission — but explicit keys in both strip lists are required per the
existing pattern for `case_severity_index`.

---

## 3. Module Logic

### 3a. Base Band from CSI Tier

Priority order (first match wins):

| Condition | base_band |
|---|---|
| `intensity.tier_key == "surgery"` OR surgery in evidence | `[5.5, 9.0]` |
| `intensity.tier_key` in `{injection, procedure, interventional}` | `[3.5, 6.0]` |
| `objective.tier_key` contains `disc` / `radiculopathy` / `herniation` | `[2.5, 4.5]` |
| `objective.tier_key` contains `soft_tissue` or any objective present | `[2.0, 3.5]` |
| Default (no_objective or CSI absent) | `[1.5, 2.5]` |

If CSI absent entirely, fall back to objective signals from evidence_graph events
(look for `diagnoses` containing disc/radiculopathy/fracture/surgery keywords, or
`intensity_flags` containing injection/surgery).

Surgery base band is a floor: even with max downward adjustments do not go below
`[5.0, 8.0]`.

### 3b. Adjustments

Step size: `0.5` default, `1.0` max per factor.
Cap: total upward ≤ `+2.0`, total downward ≥ `-2.0`.
Each adjustment adds to BOTH `low` and `high` of band.

**Upward** (sourced from structured evidence signals, never free-text):

| key | delta | source |
|---|---|---|
| `radiculopathy_documented` | +0.5 | diagnoses containing M54.x / ICD "radiculopathy" |
| `multi_level_disc_pathology` | +0.5 | 2+ distinct disc levels in diagnoses/exam_findings |
| `emg_ncs_positive` | +0.5 | exam_findings or diagnoses containing EMG/NCS positive |
| `specialist_management` | +0.5 | providers with specialty: pain mgmt/ortho/neuro |
| `injection_or_intervention` | +1.0 | injection/procedure event present AND not already in surgical base tier |
| `surgery_recommended` | +1.0 | "recommended" + surgery in promoted_findings/notes, no surgery performed |
| `work_restriction_or_disability_rating` | +0.5 | disability/TPD/restriction in exam_findings or diagnoses |
| `persistent_neuro_deficit` | +0.5 | objective neurological deficit documented in last 2 events |
| `treatment_duration_gt_180_days` | +0.5 | care span > 180 days (use DOI to last event) |
| `treatment_duration_gt_365_days` | +1.0 | care span > 365 days (replaces the +0.5 above, not additive) |

**Downward**:

| key | delta | source |
|---|---|---|
| `major_gap_in_care_gt_120_days` | -1.0 | gap > 120 days in evidence_graph gaps |
| `gap_in_care_60_120_days` | -0.5 | any gap 60–120 days |
| `delayed_first_care_gt_14_days` | -0.5 | days from DOI to first event > 14 |
| `prior_similar_injury` | -0.5 | prior injury signal in case_info or promoted_findings |
| `conservative_only_no_imaging` | -0.5 | no imaging event AND no specialist event |
| `pt_visits_lt_6` | -0.5 | PT encounter count < 6 **AND** conservative-only case **AND** no imaging **AND** no specialist; skip if any escalation present |
| `imaging_negative_or_minor` | -0.5 | imaging exists **AND** findings negative/unremarkable **AND** no objective neurological diagnosis **AND** no escalation beyond conservative care; skip if radiculopathy/disc documented |

Apply at most once per key. Do not compound.

**Guard note for `imaging_negative_or_minor`**: if `radiculopathy_documented` or
`multi_level_disc_pathology` is also active as an upward key, suppress this factor
entirely — a "small bulge" finding should not penalize a case that also has documented
neurological involvement.

**Guard note for `pt_visits_lt_6`**: do not apply if the intensity base tier is already
injection or surgical, or if specialist_management is active. Early escalation replaces
the need for visit count.

Floor: band does not go below `[1.0, 2.0]`.

### 3c. Anchor Derivation

```
risk_count = number of active downward adjustment keys applied

if risk_count >= 2:  percentile = 0.70
elif risk_count == 1: percentile = 0.80
else:                 percentile = 0.90

chosen_multiplier = low + percentile * (high - low)
anchor = round(specials_total * chosen_multiplier, -2)  # nearest $100

# Sanity clamp (band bounds):
anchor = max(anchor, specials_total * low)
anchor = min(anchor, specials_total * high)

# Floor safety (prevents under-anchoring in tight bands):
anchor = max(anchor, round(specials_total * (low + 0.25), -2))
```

If `specials_total` is absent or 0: omit `anchor` block entirely; return
posture-only output with `"anchor": null`.

### 3d. Case Strength Summary

Computed from: CSI base score, active upward keys, active downward keys.
CSI dominates; adjustments refine, not override.

```python
strength_score = (
    csi_base_0_100 * 0.6
    + len(up_keys) * 6
    - len(down_keys) * 8
)  # clamped 0–100
```

Map to band:
- 0–30 → "LOW"
- 31–55 → "MODERATE"
- 56–75 → "STRONG"
- 76–100 → "HIGH"

`primary_drivers` = human-readable labels for top 3 upward keys (sorted by delta desc),
also emitted as `confidence_drivers_ranked` with weight derived from delta (delta 1.0 →
weight 1.0, delta 0.5 → weight 0.5). Gives attorneys the "what's driving value" view.

`primary_risks` = human-readable labels for all active downward keys.

### 3e. Negotiation Strategy Map (Lookup Table)

```
STRONG or HIGH + risk_count == 0  → PUSH_HIGH_ANCHOR
STRONG or HIGH + risk_count == 1  → ASSERTIVE_WITH_PREEMPTION
STRONG or HIGH + risk_count >= 2  → STANDARD_WITH_REBUTTAL
MODERATE        + risk_count <= 1 → STANDARD
MODERATE        + risk_count >= 2 → BUILD_CASE
LOW                               → ANCHOR_NEAR_SPECIALS
```

Each strategy has a fixed `opening_strategy` string, `anticipated_defense_moves` list,
and `counter_positioning` list — all templated, zero new facts.

### 3f. Counteroffer Simulator

Given an adjuster's offer `offer_amount` and the computed `adjusted_band [low, high]`:

```
mid = specials_total * (low + high) / 2

if offer_amount < specials_total * 1.5         → LOWBALL
elif offer_amount < specials_total * low        → BELOW_RANGE
elif offer_amount <= mid                        → NEGOTIABLE
elif offer_amount <= specials_total * high      → STRONG_OFFER
else                                            → ABOVE_EXPECTATION
```

Classification is band-tied, not ratio-only. This ensures consistency with the
multiplier output the attorney already sees.

Returns `suggested_response_posture` string from template (hold firm / reduce modestly /
increase documentation emphasis). No actual dollar counter-suggestions.

### 3g. Demand Letter Draft

Template-driven. Six named blocks:

```
A. LIABILITY_SUMMARY     — from mechanism/initial_presentation section data
B. MEDICAL_OVERVIEW      — top 3 objective findings with citation IDs
C. TREATMENT_COURSE      — escalation ladder (stage labels + dates)
D. FUNCTIONAL_IMPACT     — disability/restriction signals
E. DAMAGES               — specials total formatted as "$XX,XXX"
F. DEMAND                — anchor amount: "our client demands $XXX,XXX in full settlement"
```

All content pulled from already-computed pipeline signals. No new facts introduced.
Entire block labeled:

```
INTERNAL DRAFT — DO NOT EXPORT — EDIT BEFORE SENDING
```

Block F only rendered when anchor is non-null.

**Block F hard constraints** (enforced in template, not optional):
- Never state "jury would likely award" or any verdict prediction language
- Never state "permanent injury" or "permanent disability" unless a permanency rating or
  "permanent" language is explicitly documented in the structured evidence
- Never mention the multiplier value, multiplier band, or CSI score
- Never mention the word "specials" — use "medical expenses" or "documented treatment costs"
- Opening line template only: "Based on the documented objective findings, escalation
  of care, and functional limitations, our client demands $XXX,XXX in full settlement."

---

## 4. Output Contract

```json
{
  "schema_version": "internal_demand_package.v1",
  "specials": {
    "total": 42000,
    "currency": "USD",
    "support_citation_ids": []
  },
  "strength_summary": {
    "strength_band": "STRONG",
    "confidence_score_0_100": 74,
    "primary_drivers": ["Radiculopathy documented", "Specialist management"],
    "primary_risks": ["171-day treatment gap"],
    "confidence_drivers_ranked": [
      {"key": "radiculopathy_documented", "label": "Radiculopathy documented", "weight": 0.5},
      {"key": "specialist_management", "label": "Specialist management", "weight": 0.5}
    ]
  },
  "multiplier": {
    "base_band": [2.5, 4.5],
    "adjustments": [
      {"key": "radiculopathy_documented", "direction": "up", "delta": 0.5, "support_citation_ids": []},
      {"key": "major_gap_in_care_gt_120_days", "direction": "down", "delta": -1.0, "support_citation_ids": []}
    ],
    "adjusted_band": [2.0, 4.0],
    "caps_applied": {"up_cap_hit": false, "down_cap_hit": false}
  },
  "anchor": {
    "risk_count": 1,
    "percentile_used": 0.8,
    "chosen_multiplier": 3.6,
    "suggested_demand_anchor": 151200
  },
  "negotiation_strategy": {
    "recommended_anchor_style": "ASSERTIVE_WITH_PREEMPTION",
    "opening_strategy": "Lead with objective findings and disability before addressing gap.",
    "anticipated_defense_moves": ["Minimize treatment gap", "Argue prior similar history"],
    "counter_positioning": ["Highlight continuous symptom documentation", "Emphasize escalation to specialist"]
  },
  "demand_letter_draft": {
    "label": "INTERNAL DRAFT — DO NOT EXPORT — EDIT BEFORE SENDING",
    "blocks": {
      "A_LIABILITY_SUMMARY": "...",
      "B_MEDICAL_OVERVIEW": "...",
      "C_TREATMENT_COURSE": "...",
      "D_FUNCTIONAL_IMPACT": "...",
      "E_DAMAGES": "Total Medical Specials: $42,000",
      "F_DEMAND": "..."
    }
  },
  "mode": "INTERNAL_ONLY_DO_NOT_EXPORT"
}
```

Notes:
- `adjustments` sorted by `key` before serialization.
- `anchor` key omitted (null) when specials absent.
- `demand_letter_draft.blocks.F_DEMAND` omitted when anchor is null.

---

## 5. Pipeline Integration

In `apps/worker/pipeline.py`, after the existing CSI block (around line 412–414):

```python
from apps.worker.lib.internal_demand_copilot import build_internal_demand_package

_idp = build_internal_demand_package(
    evidence_graph=evidence_graph,
    csi_internal=evidence_graph.extensions.get("case_severity_index"),
    damages_structured=specials_summary,
)
evidence_graph.extensions["internal_demand_package"] = _idp
```

Run unconditionally for both modes. The strip logic handles MEDIATION exclusion.

---

## 6. Tests — `tests/unit/test_internal_demand_copilot.py`

Minimum 38 tests across these categories:

**Base band** (5):
- Surgery intensity → `[5.5, 9.0]`
- Injection intensity → `[3.5, 6.0]`
- Disc/radiculopathy objective → `[2.5, 4.5]`
- Soft tissue objective → `[2.0, 3.5]`
- No CSI / no objective → `[1.5, 2.5]`

**Adjustments** (12):
- Single upward applied correctly
- Single downward applied correctly
- Up+down combined band math
- Up cap hit at +2.0 (try 5 upward signals)
- Down cap hit at -2.0 (try 5 downward signals)
- Surgery floor preserved after max downward pressure (min `[5.0, 8.0]`)
- Global floor `[1.0, 2.0]` respected
- treatment_duration_gt_365_days replaces gt_180 (not additive)
- `imaging_negative_or_minor` suppressed when `radiculopathy_documented` is active
- `imaging_negative_or_minor` suppressed when escalation beyond conservative exists
- `pt_visits_lt_6` suppressed when injection/surgical base tier active
- `pt_visits_lt_6` suppressed when specialist_management is active

**Anchor** (7):
- risk_count 0 → 90th percentile
- risk_count 1 → 80th percentile
- risk_count ≥ 2 → 70th percentile
- Rounds to nearest $100
- Specials absent → anchor is None, no F_DEMAND block
- Floor safety: anchor ≥ `specials * (low + 0.25)` (prevents under-anchoring in tight bands)
- Clamp upper: anchor ≤ `specials * high`

**Schema** (4):
- `schema_version == "internal_demand_package.v1"`
- `mode == "INTERNAL_ONLY_DO_NOT_EXPORT"`
- `adjustments` are sorted by `key`
- `support_citation_ids` present on each adjustment

**Strip tests** (4):
- MEDIATION `build_export_evidence_graph` output does NOT contain `internal_demand_package`
- INTERNAL mode preserves `internal_demand_package`
- `_MEDIATION_BANNED_KEYS` in orchestrator.py contains `"internal_demand_package"`
- `_VALUATION_EXTENSION_KEYS` in artifacts_writer.py contains `"internal_demand_package"`

**Strategy map** (2):
- Same inputs produce same posture every call (deterministic)
- LOW strength → "ANCHOR_NEAR_SPECIALS"

**Demand letter safety** (3):
- Block F absent when anchor is None
- Block F text does not contain "jury", "permanent", "multiplier", or "CSI"
- `confidence_drivers_ranked` weights match deltas of active upward keys

**Counteroffer** (5):
- Offer < 1.5× specials → LOWBALL
- Offer < specials × low (below band) → BELOW_RANGE
- Offer ≤ band midpoint → NEGOTIABLE
- Offer ≤ specials × high → STRONG_OFFER
- Offer > specials × high → ABOVE_EXPECTATION

---

## 7. What Does NOT Change

- `mediation_sections.py` — untouched
- MEDIATION PDF rendering — untouched
- Existing CSI / settlement_model_report / defense_attack_map modules — untouched
- All existing tests — must remain green

---

## 8. Pass33 Files Touched

| File | Change |
|---|---|
| `apps/worker/lib/internal_demand_copilot.py` | **NEW** |
| `apps/worker/pipeline.py` | Add call after CSI block |
| `apps/worker/lib/artifacts_writer.py` | Add key to `_VALUATION_EXTENSION_KEYS` |
| `apps/worker/steps/export_render/orchestrator.py` | Add key to `_MEDIATION_BANNED_KEYS` |
| `tests/unit/test_internal_demand_copilot.py` | **NEW**, ≥30 tests |
