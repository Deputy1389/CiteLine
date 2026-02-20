# Pilot Launch Command Checklist (7 Days)

Use this exactly in order. Mark each item `PASS` or `FAIL`.

## Day 1 - Environment Lock + Secrets
1. Set backend envs (staging):
```powershell
$env:HIPAA_ENFORCEMENT="true"
$env:API_INTERNAL_AUTH_MODE="jwt"
$env:API_INTERNAL_JWT_SECRET="<32+ char random secret>"
$env:API_INTERNAL_JWT_TTL_SECONDS="60"
$env:HIPAA_AUDIT_LOGGING="true"
$env:ALLOWED_HOSTS="api-staging.ontogra.com"
$env:CORS_ALLOW_ORIGINS="https://app-staging.ontogra.com"
```
Pass criteria: service starts; `/health` returns 200.

2. Set frontend envs (staging host):
```text
NEXT_PUBLIC_API_URL=https://api-staging.ontogra.com
API_URL=http://<internal-api-dns>:8000
NEXTAUTH_URL=https://app-staging.ontogra.com
AUTH_SECRET=<strong random>
API_INTERNAL_AUTH_MODE=jwt
API_INTERNAL_JWT_SECRET=<same as backend>
NEXT_PUBLIC_HIPAA_ENFORCEMENT=true
AUTH_ALLOW_DEMO_USERS=false
NEXT_PUBLIC_AUTH_ALLOW_DEMO_USERS=false
```
Pass criteria: sign-in page hides demo credentials; app loads.

## Day 2 - Deploy + Health
1. Build and push backend image:
```powershell
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <acct>.dkr.ecr.us-east-1.amazonaws.com
docker build -t ontogra-api:latest C:\Citeline
docker tag ontogra-api:latest <acct>.dkr.ecr.us-east-1.amazonaws.com/ontogra-api:latest
docker push <acct>.dkr.ecr.us-east-1.amazonaws.com/ontogra-api:latest
```
Pass criteria: image pushed successfully.

2. Update ECS service:
```powershell
aws ecs update-service --cluster ontogra-cluster --service ontogra-api-svc --force-new-deployment --region us-east-1
```
Pass criteria: tasks healthy in target group.

## Day 3 - Core Workflow Test (Staging)
1. Run flow in app:
   - Sign in
   - Create case
   - Upload packet PDF
   - Start run
   - Download chronology PDF
Pass criteria: full flow works with no 401/403/500.

2. API sanity:
```powershell
curl https://api-staging.ontogra.com/health
```
Pass criteria: returns `{"status":"ok"...}`.

## Day 4 - 10-Packet Rehearsal
1. Process 10 representative packets.
2. Record per packet:
   - runtime
   - run status (`success|partial|failed`)
   - major quality defects count
Pass criteria: failure rate <= 5%, no high-severity legal defect.

## Day 5 - Security Verification
1. Negative tests:
   - remove internal auth token in BFF call -> expect 401
   - wrong firm context -> expect 403
2. Check audit logs:
   - request id
   - user id
   - firm id
   - status and latency
Pass criteria: all negative tests blocked and logged.

## Day 6 - Pilot Dry Run (Ops)
1. On-call owner assigned.
2. Incident channel live.
3. Rollback command verified:
```powershell
aws ecs update-service --cluster ontogra-cluster --service ontogra-api-svc --task-definition <previous-task-def> --region us-east-1
```
Pass criteria: rollback command tested in staging.

## Day 7 - Launch Readiness Decision
Go if all are true:
1. 10-packet rehearsal passed.
2. Security negative tests passed.
3. No unresolved P0/P1 defects.
4. BAA + legal prerequisites complete.

If any fail: do not launch.

