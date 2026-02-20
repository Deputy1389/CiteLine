# Pilot Output QA Rubric (Attorney-Facing Chronologies)

Score each packet on this rubric. Any `FAIL` in a Critical item is auto-reject.

## Critical (Auto-Fail if any FAIL)
1. Injury Scope Completeness
Pass: primary injuries include all major body regions from ED chief complaint/intake.
Fail example: only lumbar listed when complaint includes neck + lumbar.

2. No Fabricated Facts
Pass: every major fact is traceable to cited source text.
Fail: treatment/procedure appears without support in records.

3. Timeline Integrity
Pass: events are chronologically coherent and material dates are correct.
Fail: impossible sequence or materially wrong date ordering.

4. Citation Presence
Pass: all high-impact claims (incident, surgeries, imaging findings, discharge status) have citations.
Fail: uncited high-impact assertions.

5. Patient Boundary Integrity
Pass: no cross-patient leakage in multi-patient packets.
Fail: events attributed to wrong patient.

## High Priority Quality
1. Case Summary Accuracy
Pass: DOI/mechanism/primary injuries/treatment window align with source packet.

2. Top Case-Driving Events
Pass: items are legally material and not boilerplate noise.

3. Contradictions/Issue Flags
Pass: important contradictions are surfaced, not hidden.

4. Readability for Litigation
Pass: concise, professional, directly usable by legal team.

## Scoring
- Critical: 5 items, pass/fail only.
- High Priority: score each 0-2.
  - 2 = strong
  - 1 = acceptable with edits
  - 0 = poor
- Suggested thresholds:
  - Launch-ready packet: all Critical pass + High Priority >= 6/8
  - Needs review: all Critical pass + High Priority 4-5/8
  - Reject: any Critical fail or High Priority <= 3/8

## Reviewer Form (copy/paste)
```text
Packet ID:
Reviewer:
Date:

Critical:
- Injury Scope Completeness: PASS/FAIL
- No Fabricated Facts: PASS/FAIL
- Timeline Integrity: PASS/FAIL
- Citation Presence: PASS/FAIL
- Patient Boundary Integrity: PASS/FAIL

High Priority (0-2):
- Case Summary Accuracy:
- Top Case-Driving Events:
- Contradictions/Issue Flags:
- Readability for Litigation:

Total High Priority Score: __ / 8
Decision: LAUNCH-READY / NEEDS-REVIEW / REJECT
Notes:
```

