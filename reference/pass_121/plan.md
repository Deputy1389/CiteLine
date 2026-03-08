# Pass 121 Plan

## Goal

Run a fresh small live packet smoke against the currently deployed `www.linecite.com` path and record exactly what happens.

## Scope

- No feature work.
- No renderer/pipeline changes.
- Validate current live upload + run + artifact fetch path only.

## Steps

1. Build a small packet sample:
   - one clean packet
   - one degraded scan packet
2. Run `PacketGenerator/run_cloud_validation.py` into `reference/pass_121/cloud_batch`.
3. Capture per-run artifacts:
   - `upload.json`
   - `run_started.json`
   - `run_final.json`
   - `runs_list.json`
   - `exports_latest.json`
   - `evidence_graph.json` when available
   - `chronology.pdf` when available
4. Write summary:
   - packet attempted
   - terminal status
   - artifact retrieval success
   - whether this validates only the currently deployed path or specifically the new direct-upload path

## Success Criteria

- At least one live packet reaches terminal status.
- Artifact retrieval works for at least one run.
- Summary explicitly states the deployment boundary and does not overclaim live rollout status.
