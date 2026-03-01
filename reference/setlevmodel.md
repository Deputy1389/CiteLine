The Purpose (Stripped Down)

The purpose of a Settlement Leverage Model is to:

Quantify negotiation power

Identify carrier attack vectors

Determine optimal timing

Guide demand positioning

Reduce under-settlement

That’s it.

Everything else is noise.

What It Is NOT

It is not:

A case value estimator

A verdict predictor

A sympathy engine

A generic AI summary

It’s a leverage assessor.

Value ≠ leverage.

A $20k meds case can have strong leverage.
A $150k surgery case can have weak leverage.

The model exists to measure negotiation strength, not total damages.

What It Actually Measures

A proper leverage model scores structural factors like:

1️⃣ Liability Certainty

Clear fault?

Police report support?

Independent witness?

Comparative negligence risk?

Leverage collapses if liability is shaky.

2️⃣ Objective Damages

MRI findings

EMG confirmation

Fracture

Surgical intervention

Hardware implantation

Carriers fear objective injury.

3️⃣ Escalation Trajectory

Conservative → injection → surgery?

Or PT and discharge?

Escalation increases pressure.

4️⃣ Continuity & Credibility

Gaps?

Compliance?

“Improving” notes?

Prior injury overlap?

Defense ammunition reduces leverage.

5️⃣ Permanency Signals

Future care recommended?

Surgical candidacy?

Chronic pain pattern?

Impairment rating?

Future exposure = carrier risk.

What It Outputs

A leverage model should output structured decisions like:

Settlement Posture: PUSH / HOLD / BUILD / FILE

Defense Risk Rank: Top 3 vulnerabilities

Pressure Multipliers: Surgery, Objective Imaging, Wage Loss

Weakness Flags: Gap risk, pre-existing overlap

Leverage Index: 0.00–1.00

It tells the lawyer:

“Here is how strong your negotiation hand actually is.”

Why This Matters

Most PI attorneys negotiate by instinct.

The leverage model:

Makes instinct measurable

Makes risk visible

Makes timing strategic

Makes demand framing intentional

It transforms:

“Feels strong.”

into

“Strong because X, Y, Z. Weak because A, B.”

That’s optimization.

The Core Philosophy

Settlement leverage =

Carrier fear × Plaintiff credibility × Exposure uncertainty
minus
Defense ammunition

Your model quantifies each variable.

The Real Strategic Purpose for Linecite

Chronology tells you what happened.

Settlement Leverage Model tells you:

When to push.

When to wait.

When to fix weaknesses.

When to file.

It is the bridge between medical facts and negotiation behavior.



You’re getting:

Formal SLM v1 Spec

Exact Input Schema

First Deterministic Scoring Equation

No fluff. Just architecture.

1️⃣ Settlement Leverage Model v1

Formal Specification

Purpose

To compute a deterministic, auditable Settlement Leverage Index (SLI) that quantifies negotiation pressure based solely on structured case signals derived from the evidence graph.

No prose.
No generative reasoning.
No hallucination surface.

Design Principles

Deterministic only

Citation-bound inputs

Fully auditable intermediate components

Modular scoring buckets

No external valuation data required

Core Outputs
{
  "settlement_leverage_index": 0.74,
  "liability_strength": 0.88,
  "damages_objectivity": 0.81,
  "treatment_continuity": 0.76,
  "defense_risk_index": 0.29,
  "escalation_signal": 0.67,
  "permanency_signal": 0.52,
  "recommended_posture": "HOLD_FOR_ESCALATION",
  "confidence_score": 0.92
}

All fields derived from sub-scores.

Core Buckets

SLM v1 evaluates 6 structural domains:

Liability Certainty

Objective Injury Strength

Escalation Trajectory

Treatment Continuity

Defense Vulnerability

Permanency / Future Exposure

Each produces a normalized 0–1 score.

2️⃣ Exact Input Schema

This layer consumes structured signals only.

No raw OCR text.

Input Contract
{
  "liability": {
    "police_report_support": true,
    "independent_witness": false,
    "comparative_fault_risk": 0.15
  },
  "medical": {
    "mri_positive": true,
    "emg_positive": false,
    "fracture": false,
    "surgery_performed": false,
    "injection_performed": true,
    "hardware_implanted": false
  },
  "treatment": {
    "total_visits": 42,
    "treatment_duration_days": 180,
    "gap_over_30_days": false,
    "compliance_rate": 0.93
  },
  "prior_injury": {
    "similar_body_part_prior": true,
    "documentation_overlap_score": 0.40
  },
  "future_care": {
    "future_surgery_recommended": false,
    "impairment_rating_present": false
  },
  "economic": {
    "documented_wage_loss": 18000,
    "lost_work_days": 47
  }
}

Every field must map to evidence graph citations.

If not citation-backed → cannot enter model.

3️⃣ Deterministic Scoring Equation (v1)

We compute each domain separately.

A. Liability Strength
base = 0.5

+0.25 if police_report_support
+0.15 if independent_witness
- comparative_fault_risk * 0.5

Clamp 0–1
B. Damages Objectivity
score = 0

+0.30 if mri_positive
+0.20 if emg_positive
+0.40 if fracture
+0.50 if surgery_performed
+0.25 if injection_performed
+0.40 if hardware_implanted

Cap at 1.0

Surgery overrides most other weightings.

C. Escalation Signal
0.2 baseline

+0.3 if injection_performed
+0.5 if surgery_performed
+0.2 if treatment_duration_days > 120

Cap 1.0
D. Treatment Continuity
score = compliance_rate

-0.25 if gap_over_30_days

Clamp 0–1
E. Defense Risk Index
risk = 0

+0.4 if similar_body_part_prior
+ documentation_overlap_score * 0.4
+0.3 if gap_over_30_days

Cap 1.0

This is inverse leverage.

F. Permanency Signal
score = 0

+0.6 if future_surgery_recommended
+0.4 if impairment_rating_present

Cap 1.0
Final Settlement Leverage Index

Weighted composite:

SLI = 
  (liability_strength * 0.25)
+ (damages_objectivity * 0.25)
+ (escalation_signal * 0.15)
+ (treatment_continuity * 0.10)
+ (permanency_signal * 0.15)
- (defense_risk_index * 0.20)

Clamp 0–1.

Posture Mapping
SLI >= 0.75 → PUSH_HIGH_ANCHOR
0.60–0.74 → STRONG_STANDARD_DEMAND
0.45–0.59 → BUILD_CASE
0.30–0.44 → FIX_WEAKNESSES
< 0.30 → HIGH_RISK_SETTLEMENT

No generative logic.

Pure mapping.

Why This Is Safe

Fully deterministic

No persuasive language

No hallucination risk

All inputs citation-bound

Fully explainable

You can log every component score.

If a lawyer asks “why 0.74?” you show them the math.

That builds trust.

What This Unlocks

Once this exists:

Damages graph reads SLI signals

Demand letter pulls structured strengths

Negotiation simulation uses leverage posture

Without this layer, everything else is vibes.

With it, you have a negotiation instrument.