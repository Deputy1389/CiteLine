# Pilot Go-Live Runbook (Ontogra)

## Objective
Run pilot safely with attorney-facing outputs that are stable, citeable, and operationally supportable.

## T-24 Hours
1. Freeze deploys except critical fixes.
2. Verify production env vars for API and frontend.
3. Confirm DB backups and S3 versioning are enabled.
4. Validate CORS allowlist includes only production frontend domains.

## T-4 Hours
1. Deploy latest backend image to ECS service.
2. Deploy latest frontend build.
3. Run smoke flow end-to-end:
   - Sign in.
   - Create matter.
   - Upload packet.
   - Generate chronology.
   - Export PDF.
4. Review 3 generated PDFs manually for:
   - Accurate injury scope in summary.
   - Event chronology sorted by date.
   - Citations present on material assertions.

## T-1 Hour
1. Check CloudWatch dashboards:
   - API 5xx rate.
   - p95 latency.
   - ECS task restarts.
2. Confirm alarms route to on-call channel.
3. Post launch status and rollback instructions in internal channel.

## Launch Window
1. Enable pilot users.
2. Monitor first 10 real packets.
3. Sample-review at least 5 outputs with legal QA checklist:
   - No fabricated facts.
   - No missing principal injuries from chief complaint/intake.
   - Causal chain statement supported by cited records.
   - Top case-driving events are materially relevant.

## Rollback Triggers
1. API error rate > 2% for 10 minutes.
2. Chronology generation failure rate > 5% for 10 packets.
3. Any high-severity legal quality defect (hallucinated treatment, wrong DOI, missing primary injury axis).

## Rollback Steps
1. Scale pilot access down (disable pilot cohort).
2. Redeploy prior ECS task definition revision.
3. Repoint frontend env if needed.
4. Announce incident + ETA for fix.

## Post-Launch (First 24 Hours)
1. Review 20 pilot outputs, log defects by category.
2. Ship hotfixes in batched windows.
3. Publish daily quality scorecard:
   - citation coverage
   - contradiction flags
   - injury scope completeness
   - attorney acceptance rate

