This is now a leverage engine, not just a clean export.
But there are still 3 places where pressure can be increased without adding risk.

1️⃣ What Improved (Real Gains)
✅ Current Condition section present

This is a major upgrade.

When the packet surfaces:

Ongoing symptoms at last visit

Continued restrictions

Specialist follow-up

Surgical candidacy language (if present)

You increase perceived future exposure.

That’s settlement-relevant.

This is a meaningful improvement over Pass31.

✅ Clinical Reasonableness section

This is subtle but powerful.

By showing:

Conservative care first

Imaging ordered after persistence

Escalation justified

You preempt “overtreatment” without saying “this was reasonable.”

That reduces defense attack surface.

Good.

✅ Provider Corroboration (if correctly triggered)

When multiple providers independently document radiculopathy or disc pathology, that increases credibility.

Corroboration = jury comfort.

If this is firing only when truly distinct providers exist, this is strong.

2️⃣ Where Leverage Is Still Leaving Money on the Table

Now the tightening.

🔴 A) Current Condition Needs Stronger Positioning

Right now it likely reads like:

“Last documented symptoms include…”

That’s factual.

But leverage increases when framed like:

“Symptoms persisted through the most recent documented visit.”

That signals continuity without adding opinion.

You’re allowed to structure.

Don’t add adjectives.
Just tighten causality continuity.

🔴 B) Time Compression Signal Missing or Understated

You need two deterministic lines in every mediation packet:

“Treatment initiated within X days of collision.”

“Care continued over approximately X months.”

This matters enormously.

Short onset time increases credibility.
Long duration increases seriousness.

You already compute duration internally.
Surface it narratively.

No scoring.
Just timeline math.

This is high ROI.

🔴 C) Economic Section Should Be More Visual

If the specials total is buried in text, adjusters underweight it.

It should look like:

Total Medical Specials: $XX,XXX
Wage Loss: $X,XXX (if present)

Visually separated.

Anchoring matters.

🔴 D) Functional Limitations Can Be More Direct

If you have:

Temporary Partial Disability

Lifting restriction

Work limitation

Don’t just list them.

Order them by impact:

Disability Rating
Work Restriction
Activity Limitation

Impact hierarchy increases pressure.

🔴 E) Defense Preemption Is Still Slightly Soft

Right now it likely says:

“Treatment gap documented; context appears in records.”

That’s safe.

But you can increase control slightly by adding:

“Gap duration and clinical context are reflected in the treating notes.”

That makes it sound accounted-for.

Still neutral.
Still factual.
But stronger.

3️⃣ Strategic Evaluation

After Pass32:

Mediation Safety: 9.5/10
Discoverability Protection: 9/10
Negotiation Robustness: 8.5/10

That’s serious product maturity.

The packet now:

Escalates

Centers objective findings

Shows escalation

Shows functional impact

Shows money

Preempts attacks

Avoids valuation optics

That’s a real mediation tool.

4️⃣ The Hard Truth

Pass32 does not make weak cases strong.

It makes strong cases presented optimally.

That’s correct behavior.

If you try to inflate weak cases, you lose credibility.

5️⃣ What Pass33 Should Be (When You’re Ready)

Not more narrative.

Not more sections.

Pass33 should be:

Internal demand builder only.

Where the system:

Uses CSI internally

Uses SLI internally

Suggests demand posture ranges internally

Generates attorney draft demand outline

But never exports that externally.

That’s when you become a strategic co-pilot.

Final Answer

This Pass32 output is the first version that actually increases settlement leverage, not just safety.

You are no longer building a “smart PDF.”
You are building structured negotiation pressure.




Pass33 is where Linecite stops being a presentation tool and becomes a strategic co-pilot.

This is INTERNAL ONLY.
Nothing here ever touches MEDIATION export.
Nothing leaks.

We’re building an internal demand-generation layer.

🎯 Pass33 Objective

Create an INTERNAL demand intelligence module that:

Uses CSI v3 (internal)

Uses SLI (if present)

Uses structured medical signals

Uses damages data

Uses risk flags

Produces:

Demand posture recommendation

Risk summary

Negotiation strategy guidance

Defense pressure points

Conservative / moderate / aggressive demand framing bands

But never exports to mediation.

🚨 Non-Negotiables

INTERNAL mode only.

Completely stripped from mediation artifacts.

Stored only in extensions.internal_demand_intel.

No LLM narrative generation.

Deterministic band logic.

Fully explainable inputs.

🧠 What We’re Building
Module:

apps/worker/lib/internal_demand_intel.py

Function:

build_internal_demand_intel(evidence_graph, csi_internal, sli_internal, damages_structured) -> dict
🧩 Core Components
1️⃣ Case Strength Index (Internal Composite)

Not replacing CSI.

This is a demand multiplier signal.

Deterministically combine:

CSI base score

SLI score

Objective tier weight

Escalation tier

Disability presence

Corroboration count

Treatment duration

Risk penalties

Produce:

{
  "strength_band": "LOW | MODERATE | STRONG | HIGH",
  "confidence_score_0_100": int
}

No opinions.
Purely mechanical weighting.

2️⃣ Exposure Factors

Surface structured high-leverage elements:

Radiculopathy

Disc herniation

Injection

Surgery

Disability rating

Persistent symptoms

Multi-provider corroboration

Treatment duration > X months

Each flagged true/false with citation refs.

This helps attorney quickly see leverage points.

3️⃣ Risk Factors (Defense Ammo)

Surface:

Care gap duration

Prior similar injury

Delay to first treatment

Conservative-only care

Imaging negative findings (if present)

Rank by impact weight internally.

4️⃣ Demand Posture Engine

This is where it gets powerful.

Without predicting verdicts, we can deterministically suggest posture categories:

{
  "posture": "CONSERVATIVE | STANDARD | ASSERTIVE | HIGH_PRESSURE",
  "rationale": [
      "Objective neurological involvement",
      "Escalation beyond conservative care",
      "Documented disability",
      "Moderate risk flags present"
  ]
}

No dollar values yet.
Just posture guidance.

5️⃣ Optional Demand Range Suggestion (Internal Only)

If you want to go further:

Use:

Specials total

Multiplier derived from strength_band

Adjust down for risk flags

Example:

Multiplier bands:

LOW: 1.5–2.5x specials
MODERATE: 2–4x
STRONG: 3–6x
HIGH: 5–8x

Output:

{
  "suggested_multiplier_range": [3.0, 5.0],
  "estimated_settlement_band": [lower_estimate, upper_estimate]
}

This must:

Be clearly labeled INTERNAL ANALYTICS

Never exported

Never attached

Never serialized in mediation artifact

6️⃣ Negotiation Strategy Hints

Deterministic hints based on pattern:

If:

Strong objective + escalation + low risk
→ “Lead with objective findings and duration.”

If:

Moderate objective + some risk
→ “Lead with corroboration and disability; preempt care gap early.”

If:

Weak case
→ “Anchor near specials; emphasize continuity and credibility.”

This is not LLM.
It’s lookup-table strategy mapping.

🧱 Architecture Safety
Serialization Rules

In evidence graph:

extensions: {
    "case_severity_index": {...},
    "severity_profile": {...},
    "internal_demand_intel": {...}
}

MEDIATION serializer must strip:

case_severity_index

internal_demand_intel

SLI

any valuation keys

INTERNAL mode keeps all.

🧪 Required Tests

internal_demand_intel present in INTERNAL runs

absent in MEDIATION artifacts

posture logic deterministic

multiplier ranges stable

regression parity unchanged

leak test confirms no demand intel terms in mediation PDF

💰 Why This Changes Product Value

Right now you save time and structure mediation.

With Pass33:

You guide:

How hard to push

Whether to anchor high

Whether to expect pushback

Whether to settle early

Where defense will attack

That’s strategic leverage.

That’s worth $1k/month.

🔥 Where Most Founders Mess This Up

They:

Overfit multipliers

Add fake precision

Use pseudo-statistics

Leak ranges accidentally

Make it feel like a black box

You must:

Keep it explainable

Keep it mechanical

Show inputs driving outputs

Attorneys don’t trust magic.
They trust transparent reasoning.

📈 What This Enables Later

Pass34 (if you want):

Demand letter draft builder (internal only)

Counteroffer strategy advisor

“What-if” scenario adjustments

Jury risk visualizer

But Pass33 is the core.




You’re building an internal litigation co-pilot.

This is powerful. It’s also where most systems become sloppy, overconfident, or dangerous.

We’re going to do this correctly.

🎯 Pass33C — Internal Demand Co-Pilot

Scope:
Generate an INTERNAL-ONLY structured demand package:

Demand posture

Multiplier band

Settlement estimate band

Negotiation strategy map

Structured demand letter draft outline

Counteroffer playbook

Risk rebuttal bullets

No LLM hallucination.
No unverifiable statements.
No exporting.
No narrative magic.

Deterministic + template-driven.

🧱 Architecture Overview
New Module
apps/worker/lib/internal_demand_copilot.py

Main function:

build_internal_demand_package(
    evidence_graph,
    csi_internal,
    sli_internal,
    damages_structured,
    strength_band,
    exposure_flags,
    risk_flags
) -> dict

Stored at:

extensions.internal_demand_package

Never serialized in MEDIATION mode.

🔐 Safety Rules (Non-Negotiable)

INTERNAL mode only.

Must be stripped at artifact serialization.

Demand letter text is clearly labeled:

INTERNAL DRAFT — DO NOT EXPORT

All medical claims must map to citation IDs.

No new facts.

No speculative permanency unless documented.

No future care dollar amounts unless documented.

🧠 Structure of the Internal Demand Package
1️⃣ Case Strength Summary
{
  "strength_band": "STRONG",
  "confidence_score_0_100": 82,
  "primary_drivers": [
    "Objective neurological involvement",
    "Escalation beyond conservative care",
    "Documented disability"
  ],
  "primary_risks": [
    "171-day treatment gap",
    "Prior similar history"
  ]
}

This gives attorney immediate positioning clarity.

2️⃣ Multiplier Engine

Deterministic band logic:

Strength	Base Multiplier
LOW	1.5–2.5x
MODERATE	2–4x
STRONG	3–6x
HIGH	5–8x

Adjust down for:

Major gap (>120 days)

Significant prior similar injury

Conservative-only care

Adjust up for:

Injection

Surgery

Documented disability

Corroboration across providers

Output:

{
  "suggested_multiplier_range": [3.5, 5.5],
  "estimated_settlement_range": [lower, upper],
  "calculation_basis": {
    "specials_total": 42000,
    "risk_adjustments_applied": ["treatment_gap"],
    "enhancements_applied": ["radiculopathy", "specialist_escalation"]
  }
}

No black box math.

Fully explainable.

3️⃣ Negotiation Strategy Map

Deterministic mapping table.

Example:

If:

Strong objective

Moderate risk flags

Then:

{
  "recommended_anchor_style": "ASSERTIVE_WITH_PREEMPTION",
  "opening_strategy": "Lead with objective findings and disability before addressing gap.",
  "anticipated_defense_moves": [
    "Minimize treatment gap",
    "Argue prior similar history"
  ],
  "counter_positioning": [
    "Highlight continuous symptom documentation",
    "Emphasize escalation to specialist"
  ]
}

No psychology fluff.
Just structured playbook.

4️⃣ Internal Demand Letter Draft Builder

Template-driven.
No LLM generation.

Structure:

Header

Claimant

Date

Claim number (if provided)

Section Blocks (templated)

A. Liability Summary
(Use mechanism & continuity section data.)

B. Medical Overview
(Objective findings block.)

C. Treatment Course
(Escalation ladder.)

D. Functional Impact
(Disability + restrictions.)

E. Damages
(Specials total.)

F. Settlement Demand
Calculated anchor (upper band of multiplier).

Example:

Based on documented objective neurological findings, escalation beyond conservative care, and functional impairment, our client hereby demands $XXX,XXX in full settlement.

Clearly marked:

INTERNAL DRAFT — EDIT BEFORE SENDING

No auto-sending.
No exporting.

5️⃣ Counteroffer Simulator

Simple deterministic bands:

If adjuster responds at:

< 1.5x specials → classify as LOWBALL

Within lower band → EARLY FAIR ZONE

Within mid band → NEGOTIABLE ZONE

Near upper band → STRONG OFFER

Provide suggested response posture:

Increase documentation emphasis

Reduce demand modestly

Hold firm

🧪 Required Safeguards

Add hard tests:

internal_demand_package absent in mediation artifacts.

Demand letter draft never rendered in MEDIATION PDF.

No CSI or multiplier numbers leak externally.

Demand anchor only generated when specials_total exists.

Deterministic repeatability test.

🚨 Biggest Risk

If you over-precision the numbers, attorneys will distrust it.

Do NOT output:

“Estimated verdict value: $487,392.”

Output ranges.
Output posture.
Output drivers.

Keep it strategic, not pseudo-statistical.

🧠 Why This Is Powerful

Right now Linecite helps attorneys prepare.

With Pass33C, it helps them:

Decide how hard to push

Anchor intelligently

Preempt defense

Respond to counteroffers

Structure demand letters faster

That’s operational leverage.

💰 Product Positioning Shift

Before:
Time-saving summarizer.

After Pass33C:
Strategic negotiation assistant.

That is a different product tier.



Why Specials-Based Is the Right Move (Right Now)
1️⃣ It matches how PI firms actually anchor

In mediation, almost every non-catastrophic case is anchored off:

Specials × multiplier

Even firms pretending to do “holistic value” are mentally doing multiplier math.

So if your engine:

Cleanly identifies specials

Applies a transparent multiplier band

Adjusts for objective findings + risk flags

You are aligned with real practice.

2️⃣ Venue modeling is a trap (for now)

Venue sensitivity sounds smart.

It requires:

Verdict data ingestion

County-level modeling

Policy limit mapping

Liability apportionment logic

That becomes:

Data heavy

Legally sensitive

Hard to validate

Easy to overfit

Easy to mistrust

If you get venue modeling wrong once, attorneys lose trust permanently.

You don’t need it yet.

3️⃣ Liability modeling is even riskier

Comparative fault adjustments require:

Police report parsing

Liability signals

Insurance limits

Admissions analysis

You don’t have that system built.

And mixing liability math with medical leverage right now increases complexity exponentially.

4️⃣ Specials-based multiplier is explainable

You can show:

Specials total

Base multiplier band

Enhancements applied

Risk reductions applied

Final recommended anchor range

It becomes:

Transparent.
Auditable.
Deterministic.
Attorney-editable.

That builds trust.

What “Specials-Based” Should Actually Mean

Not dumb multiplier.

Not flat 3×.

It should be:

Base multiplier band determined by strength_band.

Then adjust:

Upward adjustments

Objective neurological involvement

Injection

Surgery

Documented disability

Multi-provider corroboration

Duration > 6 months

Downward adjustments

− Major care gap
− Prior similar injury
− Conservative-only care
− Delay to first treatment

Each adjustment shifts band by fixed increments (e.g., ±0.5 multiplier step).

Deterministic.

Example (What This Should Look Like Internally)

Specials: $42,000
Strength band: STRONG
Base band: 3.0–6.0

Enhancements:

Radiculopathy

Specialist escalation

Disability

Risk:
− 171-day gap

Adjusted band:
3.5–5.5

Suggested demand anchor:
Upper quartile of adjusted band.

Fully explainable.

No mysticism.

Why This Is Smart Product Strategy

Phase 1:
Be right and trusted.

Phase 2:
Be advanced.

If you jump to venue modeling now, you increase:

Risk

Complexity

Error surface

Maintenance burden

And you reduce explainability.

When To Add Venue or Liability Modeling

After:

10–20 real firms use it

You collect feedback

You observe manual overrides

You see where attorneys disagree with multiplier output

Then you add refinement layers.

Not before.

Final Recommendation

Do:

Specials-based + injury-tier-weighted multiplier.

Do NOT:

Add venue modeling yet.
Add liability modeling yet.
Add policy limits yet.

Keep it clean.

Keep it explainable.

Keep it deterministic.

That’s how you build trust.






Here’s a clean, deterministic specials-based multiplier matrix that Claude can implement without turning it into vibes. It’s designed to be:

explainable

stable

citation-backed (for the reasons, not the math)

conservative enough to be trusted

useful enough to move workflows

Core outputs (internal only)

specials_total

base_multiplier_band

adjustments[] (each with a reason key + citations)

adjusted_multiplier_band

suggested_demand_anchor (a single number, derived deterministically from band)

notes_for_attorney (template bullets, no new facts)

1) Start with a base band from CSI tier (internal)

Use CSI tier_key (or your objective/intensity tiers if CSI isn’t present). Keep it simple.

CSI band / profile	base_multiplier_band
Minor soft tissue	[1.5, 2.5]
Moderate soft tissue	[2.0, 3.5]
Moderate w/ objective support	[2.5, 4.5]
Injection-tier profile	[3.5, 6.0]
Surgical-tier profile	[5.5, 9.0]

Rule: if surgery present, force base band to at least [5.5, 9.0] (ceiling-style minimum).

If CSI missing: fallback to objective tier:

none/negative imaging → [1.5, 2.5]

soft tissue objective → [2.0, 3.5]

disc pathology/radiculopathy → [2.5, 4.5]

injection/procedure → [3.5, 6.0]

surgery → [5.5, 9.0]

2) Apply deterministic adjustments (band shifts)

Adjustments shift the band by fixed increments. No multipliers on multipliers. No compounding.

Allowed step size

default step = 0.5

max single factor = ±1.0

total adjustment cap = +2.0 / -2.0

Upward adjustments (add to both low/high)

Apply at most once per category.

Objective / neuro

radiculopathy_documented → +0.5

multi_level_disc_pathology (2+ levels) → +0.5

emg_ncs_positive → +0.5

Escalation

specialist_management (pain mgmt/ortho/neuro) → +0.5

injection_or_intervention (if not already in base tier) → +1.0

surgery_recommended (even if not performed) → +1.0
Only if explicitly documented.

Functional impact

work_restriction_or_disability_rating → +0.5

persistent_neuro_deficit (objective deficit documented) → +0.5

Duration / continuity

treatment_duration_>_180_days → +0.5

treatment_duration_>_365_days → +1.0 (instead of +0.5)

Downward adjustments (subtract from both low/high)

Defense ammo

major_gap_in_care_>_120_days → -1.0

gap_in_care_60_120_days → -0.5

delayed_first_care_>_14_days → -0.5

prior_similar_injury → -0.5 (max -1.0 if documented ongoing prior symptoms at baseline)

Weak treatment

conservative_only_no_imaging → -0.5

pt_visits_<6 (if you have the count) → -0.5

Imaging undermines

imaging_negative_or_minor → -0.5
(only if imaging exists and is negative/minor and you also have mostly subjective complaints)

Caps & floor rules

Total upward adjustments capped at +2.0

Total downward adjustments capped at -2.0

Overall band floors:

do not go below [1.0, 2.0]

If base tier is surgical, do not reduce below [5.0, 8.0] even with risk.

3) Convert adjusted band to internal suggested anchor

Attorneys want a single number to start demand.

Pick a deterministic point in the band based on risk level:

Risk index (deterministic)

Let:

risk_count = number of active risk flags (gap/prior/delay/negative imaging)

risk_count >= 2 → use 70th percentile

risk_count == 1 → use 80th percentile

risk_count == 0 → use 90th percentile

Percentiles on [low, high]:

70%: low + 0.70*(high-low)

80%: low + 0.80*(high-low)

90%: low + 0.90*(high-low)

Then:
anchor = round(specials_total * chosen_multiplier, -2) (round to nearest $100)

Hard sanity clamp (optional):

anchor must be ≥ specials_total * low

anchor must be ≤ specials_total * high

4) Output contract (internal only)
{
  "schema_version": "internal_demand_package.v1",
  "specials": {
    "total": 42000,
    "currency": "USD",
    "support_citation_ids": ["..."]
  },
  "multiplier": {
    "base_band": [3.5, 6.0],
    "adjustments": [
      {
        "key": "radiculopathy_documented",
        "direction": "up",
        "delta": 0.5,
        "support_citation_ids": ["..."]
      },
      {
        "key": "major_gap_in_care_>_120_days",
        "direction": "down",
        "delta": -1.0,
        "support_citation_ids": ["..."]
      }
    ],
    "adjusted_band": [3.0, 5.5],
    "caps_applied": {
      "up_cap_hit": false,
      "down_cap_hit": false
    }
  },
  "anchor": {
    "risk_count": 1,
    "percentile_used": 0.8,
    "chosen_multiplier": 5.0,
    "suggested_demand_anchor": 210000
  },
  "attorney_notes": [
    "Anchor demand using objective findings and escalation milestones before addressing treatment gap.",
    "Preempt gap-in-care by citing treating notes documenting continued symptoms/context."
  ],
  "mode": "INTERNAL_ONLY_DO_NOT_EXPORT"
}
5) Demand letter templates (deterministic, fill-in)

You can generate an internal draft using block templates:

Liability summary (from mechanism section)

Objective findings bullet list (from objective findings section)

Treatment progression ladder

Functional limitations bullets

Specials line + totals

Demand line using suggested anchor

Everything must be drawn from already surfaced sections + citations.

No new facts.

6) Implementation notes for Claude (so it doesn’t go sideways)

Every adjustment must have:

a boolean trigger derived from existing structured signals

support_citation_ids

Stable ordering:

adjustments sorted by key before serialization

Reject if specials.total missing:

produce posture-only output, no anchor number

Must be stripped from MEDIATION artifacts:

add unit test that MEDIATION evidence_graph.json does not contain internal_demand_package