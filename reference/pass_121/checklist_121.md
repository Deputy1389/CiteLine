# Pass 121 Checklist

## PHASE 1 - DIAGNOSE

### 0a. System Model

- Major components involved:
  - `PacketGenerator/*` builds and renders synthetic packets.
  - `tmp/run_cloud_case_api.ts` logs into `www.linecite.com`, creates a matter, uploads a PDF, starts a run, polls run status, and downloads artifacts.
  - Production website currently fronts upload traffic.
  - Production API/worker process the packet and emit `exports/latest`, `evidence_graph.json`, and chronology PDF artifacts.
- Data flow:
  - Generator renders packet PDF -> browser/API upload -> matter document row -> run start -> worker processing -> artifact fetch.
- Ownership of state:
  - Packet bytes: generator output folder / uploaded storage object.
  - Run state: production API/database.
  - Artifacts: worker + storage.
- Boundaries:
  - Generator ends at packet file creation.
  - Live upload and processing start at `www.linecite.com`.

Weakest boundary:
- Local code vs deployed production. A local repo change can appear complete while live upload behavior is still running older code.

### 0b. Failure Mode Analysis

1. Live deploy does not include local upload/sweeper changes.
   - Severity: high
   - Probability: high
   - Detectability: medium
   - Blast radius: all smoke conclusions become misleading
2. Upload path still uses old body-proxy route and fails on larger files.
   - Severity: high
   - Probability: high
   - Detectability: high
   - Blast radius: large packet validation blocked
3. Smoke packet completes but artifacts are missing.
   - Severity: high
   - Probability: medium
   - Detectability: high
   - Blast radius: review UI/export validation blocked
4. Browser login/upload harness flakes.
   - Severity: medium
   - Probability: medium
   - Detectability: high
   - Blast radius: validation delay only
5. Run reaches terminal `needs_review` unexpectedly because of pipeline quality gates.
   - Severity: medium
   - Probability: high
   - Detectability: high
   - Blast radius: impacts interpretation, not harness correctness

Highest-risk failure class:
- Trust erosion risk from claiming the new upload/sweeper path is live when production may still be on older code.

### 0c. Architectural Smell Detection

- Hidden state: deployment status is external to the repo.
- Unclear ownership: production enablement depends on Render/Vercel state, not only code.
- Silent fallbacks masking real errors: packet uploads can still succeed through old paths, hiding that the new direct-upload path is not live.

### 0d. Dangerous Illusion Check

Most dangerous illusion:
- A successful local code change looks like a production fix even when the live site has not been redeployed from GitHub `main`.

## PHASE 2 - DESIGN

### PASS TITLE:

Pass 121 - Live Packet Smoke Validation

### 1. System State

- Stage: validation / production smoke
- Allowed to add features this pass: No
- This pass is safer as hardening/validation because the primary risk is false confidence about live behavior.

### 2. Failure Class Targeted

- [ ] Data integrity failure
- [ ] Narrative inconsistency
- [ ] Required bucket miss
- [ ] Determinism variance
- [ ] Export leakage
- [ ] Signal distortion
- [x] Trust erosion risk
- [ ] Review burden inflation
- [ ] Performance bottleneck
- [ ] Architectural coupling / layer bleed

Primary:
- Trust erosion risk

Why highest risk now:
- The repo contains upload/sweeper changes, but production proof still requires a real cloud smoke on the currently deployed system.

### 3. Define the Failure Precisely

- Failing condition today:
  - We do not yet have a fresh post-pass live smoke proving the current production path can ingest and process new packets after the latest upload architecture work.
- Artifact proving the issue:
  - No post-pass cloud run artifacts under a new validation folder.
- Reproducibility:
  - Systemic until a fresh cloud smoke is executed.

### 4. Define the Binary Success State

After this pass:
- It must be impossible to confuse "code complete locally" with "live path validated" for this round.
- At least one fresh live packet upload must reach terminal status and save run artifacts under `reference/pass_121/`.
- If the live path does not include the new code, that must be stated explicitly in the summary.

### 5. Architectural Move (Not Patch)

- Boundary enforcement through explicit live validation artifacts.
- This is not a feature patch. It is a production-state validation pass that records what the live system is actually doing.

### 6. Invariant Introduced

- Invariant:
  - A production claim about upload behavior must be backed by a fresh live smoke artifact set in `reference/pass_121/`.
- Enforced:
  - By this pass output and summary.
- Tested:
  - Via the live packet run harness outputs.

### 7. Tests Planned

- Live smoke runs with `tmp/run_cloud_case_api.ts` through `PacketGenerator/run_cloud_validation.py`
- Artifact-level assertions:
  - `run_final.json` exists
  - `exports_latest.json` exists
  - `evidence_graph.json` exists when API returns 200
  - chronology PDF exists when API returns 200

### 8. Risk Reduced

- [ ] Legal risk
- [x] Trust risk
- [ ] Variability
- [ ] Maintenance cost
- [x] Manual review time

How:
- Replaces assumption with observed live behavior and concrete artifacts.

### 9. Overfitting Check

- Generalizable: Yes
- Packet-specific: No, but this pass will use a small packet sample for smoke only.
- Cross-case risk: Low, as this is a validation pass rather than a code-path specialization.

### 10. Cancellation Test

- A PI firm cancels if upload behavior is unreliable or if the team claims fixes are live when they are not.
- This pass reduces that risk by proving or disproving current live readiness.

## PHASE 3 - HARDEN

### 11. Adversarial QA

- Try both clean and degraded packets.
- Distinguish upload failure from worker failure from artifact fetch failure.
- Record live limitations explicitly instead of smoothing them over.

### 12. Determinism Audit

- Nondeterminism sources:
  - live queue latency
  - browser timing
  - run polling duration
- Determinism is not guaranteed for completion time, only for artifact capture once the run reaches terminal status.

### 13. Test Coverage Gap Analysis

- Missing:
  - post-deploy proof of the new direct-upload path specifically
  - large-file smoke after deployed body-proxy bypass
- Acceptable for this pass because the goal is to measure the current deployed system, not assumed future deploy state.

## PHASE 4 - SIMPLIFY

### 14. Complexity Reduction

- No code complexity increase intended.
- Keep the pass to a small packet set and a clear summary.

### 15. Senior Engineer Review

- Blocker:
  - claiming production enablement without deploy proof
- This pass avoids that by reporting only observed live behavior.

### 16. Production Readiness Audit

- At 10,000 cases, the limiting factor remains deployed upload architecture and live queue capacity, not the validation harness itself.
