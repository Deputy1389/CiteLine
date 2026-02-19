# HIPAA Low-Risk Rollout Playbook - 2026-02-19

Goal: enable security controls progressively without destabilizing chronology generation.

## Phase 0 - Baseline (current safe state)
- Backend:
  - `HIPAA_ENFORCEMENT=false`
  - `HIPAA_AUDIT_LOGGING=true`
- Frontend:
  - `NEXT_PUBLIC_HIPAA_ENFORCEMENT=false`
  - `AUTH_ALLOW_DEMO_USERS=true`
  - `NEXT_PUBLIC_AUTH_ALLOW_DEMO_USERS=true`

Expected behavior:
- Existing flows unchanged.
- Request-level audit logs emitted by API.

## Phase 1 - Staging strictness test
- Backend:
  - `HIPAA_ENFORCEMENT=true`
  - `HIPAA_AUDIT_LOGGING=true`
  - `DATABASE_URL=<postgres>`
  - `DATA_DIR=<managed encrypted mount>`
  - `CORS_ALLOW_ORIGINS=<staging frontend origin(s)>`
- Frontend:
  - `NEXT_PUBLIC_HIPAA_ENFORCEMENT=true`
  - `AUTH_ALLOW_DEMO_USERS=false`
  - `NEXT_PUBLIC_AUTH_ALLOW_DEMO_USERS=false`

Required checks:
1. Login with non-demo auth path.
2. `List matters` works only for same firm.
3. `Create case -> upload -> run -> export` succeeds.
4. Cross-firm header mismatch returns `403`.
5. Missing headers return `401`.

## Phase 2 - Production cutover
1. Deploy backend strict config to production.
2. Deploy frontend with header injection + demo disabled.
3. Monitor for 24 hours:
   - `401` and `403` rates
   - run success/partial/fail rates
   - p95 latency

Rollback:
- Set `HIPAA_ENFORCEMENT=false` and `NEXT_PUBLIC_HIPAA_ENFORCEMENT=false`.

## What this does not complete
- BAAs (customer/vendor)
- Formal HIPAA risk analysis documentation
- Incident response legal workflow sign-off
- Final infrastructure attestations/encryption evidence

