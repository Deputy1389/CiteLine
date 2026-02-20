# Pilot Go-Live + Rollback Runbook (Non-Technical)

Audience: operations or legal ops teammate running launch day.

## Launch Window Steps
1. Confirm green checks from `readiness/Pilot_Launch_Command_Checklist_7Day.md`.
2. Notify internal team: launch start time and support owner.
3. Enable pilot cohort (approved firms/users only).
4. Watch dashboard/alerts for first 60 minutes.
5. Collect first 5 outputs and send to QA reviewer.

## What to Watch (First 2 Hours)
1. Login failures spike.
2. Upload failures.
3. Run failures.
4. Missing/incorrect citations in outputs.
5. Any legal reviewer reports "fabricated" or "critical missing injury."

## Immediate Escalation Triggers
1. API errors > 2% for 10+ minutes.
2. Run failure rate > 5% in first 10 packets.
3. Any critical legal defect in a delivered chronology.

If any trigger happens: start rollback immediately.

## Rollback Procedure
1. Pause pilot user intake (no new cases).
2. Notify channel: "Rollback started, ETA 15 minutes."
3. Technical owner runs ECS rollback:
```powershell
aws ecs update-service --cluster ontogra-cluster --service ontogra-api-svc --task-definition <previous-task-def> --region us-east-1
```
4. Verify health:
```powershell
curl https://api.ontogra.com/health
```
5. Confirm app workflow:
   - sign in
   - upload packet
   - run chronology
   - export PDF
6. Send status update: rollback complete + next investigation time.

## Communication Templates
Launch start:
```text
Pilot launch started at <time>. Monitoring closely for 2 hours. Support lead: <name>.
```

Incident:
```text
We detected a pilot issue (<short description>) at <time>. Rollback in progress. Next update in 15 minutes.
```

Resolved:
```text
Rollback complete at <time>. Service stable. We will provide root-cause and remediation plan by <time>.
```

## Post-Incident Checklist
1. Save logs + timestamps.
2. Record affected packets/users.
3. Complete root-cause summary.
4. Add preventive action item to backlog.
5. Re-run pilot readiness checklist before relaunch.
