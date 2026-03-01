param(
  [switch]$SkipUpload,
  [string]$MatterId,
  [string]$ReferenceDir = "reference"
)

$ErrorActionPreference = "Stop"

function Write-Step($msg) {
  Write-Host ""
  Write-Host "==> $msg" -ForegroundColor Cyan
}

if (-not (Test-Path $ReferenceDir)) {
  New-Item -ItemType Directory -Force -Path $ReferenceDir | Out-Null
}

if (-not $SkipUpload) {
  Write-Step "Trigger cloud run via Playwright upload (batch_029_complex_prior)"
  npx tsx scripts/pi_audit_simulation.ts
  if ($LASTEXITCODE -ne 0) { throw "pi_audit_simulation.ts failed" }

  if (-not (Test-Path "tmp/last_pi_audit_run.json")) {
    throw "tmp/last_pi_audit_run.json not found"
  }
  $runInfo = Get-Content "tmp/last_pi_audit_run.json" | ConvertFrom-Json
  $MatterId = [string]$runInfo.caseId
  if (-not $MatterId) { throw "Case ID missing from tmp/last_pi_audit_run.json" }
  Write-Host "Matter ID: $MatterId"
}

if (-not $MatterId) {
  throw "Provide -MatterId or run without -SkipUpload"
}

Write-Step "Verify review page renders nonzero events"
npx tsx tmp/check_review_case_live.ts $MatterId | Tee-Object -FilePath "tmp/review_case_check_$MatterId.json"
if ($LASTEXITCODE -ne 0) { throw "check_review_case_live.ts failed" }

Write-Step "Download PDF + evidence_graph.json to reference/"
$artifactJson = npx tsx tmp/save_live_case_artifacts.ts $MatterId
if ($LASTEXITCODE -ne 0) { throw "save_live_case_artifacts.ts failed" }
$artifact = $artifactJson | ConvertFrom-Json
$runId = [string]$artifact.runId
if (-not $runId) { throw "Run ID missing from save_live_case_artifacts output" }
Write-Host "Run ID: $runId"
Write-Host "Evidence Graph: $($artifact.evidenceGraphPath)"
Write-Host "PDF: $($artifact.pdfPath)"

Write-Step "Run A-E acceptance checks (+ new worker marker)"
$acceptOut = Join-Path $ReferenceDir "run_${runId}_acceptance_check.json"
python scripts/verify_litigation_export_acceptance.py `
  --evidence-graph $artifact.evidenceGraphPath `
  --pdf $artifact.pdfPath `
  --out $acceptOut
$acceptExit = $LASTEXITCODE
Write-Host "Acceptance report: $acceptOut"

if ($acceptExit -ne 0) {
  Write-Host "FAIL: one or more acceptance checks failed." -ForegroundColor Red
  exit $acceptExit
}

Write-Host "PASS: all acceptance checks passed." -ForegroundColor Green
