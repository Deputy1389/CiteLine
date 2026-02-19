# AWS Deployment Checklist (Ontogra)

## 1) Architecture (recommended)
- Frontend: Vercel or AWS Amplify for `C:\Eventis\Website`.
- API: ECS Fargate service behind ALB (`apps/api/main.py`).
- Storage: S3 for uploaded packets and generated outputs.
- Database: Postgres on RDS for pilot/prod (avoid SQLite for multi-instance).
- DNS/TLS: Route 53 + ACM certs.

## 2) Backend container + ECS
1. Build/push image to ECR.
2. Create ECS task definition with container port `8000`.
3. Set health check path `/health`.
4. Attach service to ALB target group.
5. Add autoscaling (CPU + request count).

## 3) Backend environment variables
- `DATABASE_URL=<rds connection string>`
- `CORS_ALLOW_ORIGINS=https://app.ontogra.com,https://www.ontogra.com`
- `CORS_ALLOW_CREDENTIALS=true`
- `HIPAA_ENFORCEMENT=true`
- `API_INTERNAL_AUTH_MODE=jwt`
- `API_INTERNAL_JWT_SECRET=<long-random-shared-secret>=32 chars`
- `API_INTERNAL_JWT_TTL_SECONDS=60`
- `HIPAA_AUDIT_LOGGING=true`
- `HIPAA_ALLOW_DEFAULT_LOCAL_STORAGE=false`

## 4) Frontend environment variables
Set in deployment platform:
- `NEXT_PUBLIC_API_URL=https://api.ontogra.com`
- `API_URL=http://<internal-api-dns>:8000` (optional, server-side optimization)
- `NEXTAUTH_URL=https://app.ontogra.com`
- `AUTH_SECRET=<strong-random-secret>`
- `API_INTERNAL_AUTH_MODE=jwt`
- `API_INTERNAL_JWT_SECRET=<same as backend>`
- `NEXT_PUBLIC_HIPAA_ENFORCEMENT=true`
- `AUTH_ALLOW_DEMO_USERS=false`
- `NEXT_PUBLIC_AUTH_ALLOW_DEMO_USERS=false`

Template file: `C:\Eventis\Website\env.production.template`

## 5) Domain wiring
1. Create ALB listener `443` with ACM cert for `api.ontogra.com`.
2. Route 53 `A/AAAA (alias)` for `api.ontogra.com` -> ALB.
3. Frontend domain `app.ontogra.com` (or root) -> hosting provider.
4. Validate TLS and CORS end-to-end from browser.

## 6) Smoke test before pilot
1. `GET https://api.ontogra.com/health` returns `{"status":"ok"...}`.
2. Login works on frontend and session persists.
3. Create case -> upload packet -> run chronology.
4. Confirm output citations and timeline ordering on 5 known packets.
5. Verify no browser CORS errors in devtools.

## 7) Launch-day guardrails
- Keep a staging stack with same infra shape.
- Enable centralized logs (CloudWatch) with request IDs.
- Add alarms: 5xx rate, latency p95, task restarts.
- Daily backup snapshot for RDS + S3 versioning.
