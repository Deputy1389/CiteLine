# HIPAA Gap Checklist (Ontogra) - 2026-02-19

This is an engineering readiness checklist, not legal advice.

## Current Verdict
- Not HIPAA-ready for production PHI today.
- You have meaningful building blocks, but multiple release blockers remain.

## Evidence-Based Gap Table
| Priority | Control Area | Status | Repo Evidence | Gap / Risk | Required Fix Before PHI Go-Live |
|---|---|---|---|---|---|
| Blocker | API authentication and authorization | Missing | `apps/api/routes/firms.py`, `apps/api/routes/matters.py`, `apps/api/routes/documents.py`, `apps/api/routes/runs.py` expose data operations without auth dependency | Any caller reaching API can create/read/modify tenant data by ID | Add mandatory auth on all API routes, enforce tenant scoping server-side, reject cross-firm access by default |
| Blocker | Demo credentials in production code path | Missing | `C:\Eventis\Website\lib\auth.ts` contains `DEMO_USERS` and static firm mapping | Credential and tenant impersonation risk | Remove demo users from prod build, use real IdP/user store, rotate secrets |
| Blocker | At-rest PHI encryption | Missing | `packages/shared/storage.py` stores uploads/artifacts on local disk `C:/CiteLine/data`; `packages/db/database.py` defaults SQLite local file | Local disk PHI may be unencrypted/unmanaged | Move uploads/artifacts to encrypted managed storage (S3 + SSE-KMS), run DB on encrypted RDS Postgres |
| Blocker | Business Associate Agreements (BAAs) | Missing evidence | No BAA artifacts in repo | Cannot lawfully process PHI for covered entities without proper BAAs | Execute BAAs with customers and all PHI-touching vendors/services |
| Blocker | Formal HIPAA Security Risk Analysis | Missing evidence | No risk analysis artifact/policy package found | Required administrative safeguard not documented | Complete and document risk analysis + risk management plan with owners and dates |
| High | Audit controls for ePHI access | Partial | App has logs and run metadata in `apps/api/main.py`, `apps/worker/pipeline.py` | No clear immutable access audit trail for who viewed/downloaded PHI | Add structured audit events (user, tenant, action, object, timestamp, IP), centralize and retain logs |
| High | Access control hardening (least privilege, MFA) | Partial | Session/auth exists in web layer (`middleware.ts`, `lib/auth.config.ts`) | No enforced MFA/role model at API and infra layers | Add RBAC claims, MFA for admin/support users, least-privilege IAM and DB roles |
| High | Incident response and breach notification runbook | Missing evidence | No formal incident/breach SOP artifact | Delayed/incorrect breach response risk | Create and test incident response + HIPAA breach notification workflow |
| High | Data retention and secure deletion | Partial | Design docs mention retention intent (`docs/pi-chronology-mvp.pipeline.md`) | No enforced policy for retention windows and deletion proofs | Implement retention scheduler + deletion logs for uploads/artifacts/backups |
| High | Secrets management | Partial | Env-driven config exists, but no managed secret store requirement in repo | Secret sprawl / leakage risk | Store all secrets in managed vault (AWS Secrets Manager/SSM), rotate keys, remove plaintext defaults |
| Medium | Transmission security | Partial | Deployment docs require HTTPS ALB; app itself does not enforce trusted upstream settings | Misconfiguration could expose data in transit | Enforce TLS-only ingress and HSTS at edge; disable plaintext listener |
| Medium | Contingency planning (backup/restore/DR) | Partial | Mentioned in `readiness/AWS_Deployment_Checklist_Ontogra.md` | Not validated by restore test | Define RTO/RPO, perform restore drills, document results |
| Medium | Vendor posture for frontend host | Unknown | Current plan discussed multiple hosts | Some hosts/plans may not support HIPAA terms/BAA | Choose vendors/services with signed BAA support for all PHI paths |

## Fast Path to "Pilot with Real PHI" (Minimum)
1. Put API behind real auth and tenant authorization checks (server-side).
2. Remove demo auth path and static credentials.
3. Migrate storage to encrypted managed services (S3 SSE-KMS + RDS encryption).
4. Complete BAAs (customers + vendors) before any PHI upload.
5. Publish incident response, retention, and access audit procedures.
6. Run a tabletop + technical validation: unauthorized-access tests, restore test, audit-log test.

## 7-Day Execution Plan
1. Day 1: AuthZ middleware on API + tenant guardrails; disable demo users.
2. Day 2: Encrypted data plane migration (S3/RDS), secrets manager integration.
3. Day 3: Audit logging schema and central log sink with retention.
4. Day 4: Retention/deletion job + verification report.
5. Day 5: Incident response and breach workflow docs + on-call assignment.
6. Day 6: Pen-test style access checks and restore drill.
7. Day 7: Legal/compliance sign-off package and go/no-go review.

## Authoritative References
- HHS Security Rule overview: https://www.hhs.gov/ocr/privacy/hipaa/administrative/securityrule/index.html
- HHS Privacy Rule overview: https://www.hhs.gov/hipaa/for-professionals/privacy/index.html
- HHS Breach Notification Rule: https://www.hhs.gov/hipaa/for-professionals/breach-notification/index.html
- HHS BAA guidance/sample provisions: https://www.hhs.gov/hipaa/for-professionals/covered-entities/sample-business-associate-agreement-provisions/index.html
- HHS FAQ (no official HIPAA certification requirement): https://www.hhs.gov/hipaa/for-professionals/faq/2003/are-we-required-to-certify-our-organizations-compliance-with-the-standards/index.html
- AWS HIPAA program information: https://aws.amazon.com/compliance/hipaa-compliance/

